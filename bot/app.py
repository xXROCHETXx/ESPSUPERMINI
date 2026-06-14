from __future__ import annotations

import asyncio
import logging
import os
from io import BytesIO

from telegram import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .github_store import GitHubConfig, GitHubStore
from .image_pipeline import ProcessedImage, load_source, process_image
from .manual_values import (
    ManualSession,
    decode_manual_session,
    encode_manual_session,
    manual_session_url,
    parse_manual_values,
)
from .state import Action, EditState, Preset, apply_action, decode_callback, encode_callback
from .telegram_media import preview_photo
from .webhook import normalize_webhook_secret


LOGGER = logging.getLogger(__name__)


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _allowed_users() -> set[int]:
    raw = _required_environment("ALLOWED_USER_IDS")
    return {int(value.strip()) for value in raw.split(",") if value.strip()}


ALLOWED_USERS = _allowed_users()
STORE = GitHubStore(
    GitHubConfig(
        token=_required_environment("GITHUB_TOKEN"),
        repository=_required_environment("GITHUB_REPOSITORY"),
        path=os.environ.get("GITHUB_PATH", "docs/display/current.epd"),
        branch=os.environ.get("GITHUB_BRANCH", "main"),
    )
)


def _authorized(user_id: int | None) -> bool:
    return user_id is not None and user_id in ALLOWED_USERS


def _manual_secret() -> str:
    return (
        os.environ.get("TELEGRAM_WEBHOOK_SECRET")
        or _required_environment("TELEGRAM_BOT_TOKEN")
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if not _authorized(user.id):
        await message.reply_text(
            f"Este bot es privado. Tu Telegram user ID es {user.id}."
        )
        return
    await message.reply_text(
        "Enviame una foto. Preparare una vista previa exacta para la pantalla "
        "296x152 y podras ajustar estilo, recorte, luz y color antes de publicar."
    )


async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if not _authorized(user.id):
        await message.reply_text("No tienes permiso para publicar en esta pantalla.")
        return

    try:
        source_bytes = await _download_image(message, context)
        state = EditState.defaults(Preset.PHOTO_BWR)
        processed = await asyncio.to_thread(_process_bytes, source_bytes, state)
        preview = BytesIO(processed.preview_png)
        preview.name = "preview.png"
        await message.reply_photo(
            photo=preview,
            caption=_caption(state, processed),
            reply_markup=_main_keyboard(state),
            reply_to_message_id=message.message_id,
        )
    except Exception as error:
        LOGGER.exception("Could not process incoming image")
        await message.reply_text(f"No pude procesar esa imagen: {error}")


async def handle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    if not _authorized(query.from_user.id):
        await query.answer("No autorizado", show_alert=True)
        return

    try:
        action, state = decode_callback(query.data)
    except (ValueError, TypeError):
        await query.answer("Este control ya no es valido. Envia la foto nuevamente.")
        return

    if action == Action.CANCEL:
        await query.answer()
        await query.message.delete()
        return

    if action in {
        Action.MENU_STYLE,
        Action.MENU_CROP,
        Action.MENU_TONE,
        Action.BACK_MAIN,
    }:
        await query.answer()
        keyboard = {
            Action.MENU_STYLE: _style_keyboard,
            Action.MENU_CROP: _crop_keyboard,
            Action.MENU_TONE: _tone_keyboard,
            Action.BACK_MAIN: _main_keyboard,
        }[action](state)
        await query.edit_message_reply_markup(reply_markup=keyboard)
        return

    if action == Action.MANUAL_VALUES:
        original = _original_message(query.message)
        if original is None or query.message is None:
            await query.answer(
                "No pude recuperar la foto original. Enviala nuevamente.",
                show_alert=True,
            )
            return
        session = ManualSession(
            callback_data=encode_callback(Action.MANUAL_VALUES, state),
            chat_id=query.message.chat_id,
            preview_message_id=query.message.message_id,
            file_id=_image_file_id(original),
        )
        session_url = encode_manual_session(session, _manual_secret())
        await query.answer()
        await _send_manual_prompt(query.message, session_url, state)
        return

    await query.answer("Procesando...")
    original = _original_message(query.message)
    if original is None:
        await query.edit_message_caption(
            caption="No pude recuperar la foto original. Enviala nuevamente."
        )
        return

    try:
        source_bytes = await _download_image(original, context)
        updated_state = apply_action(action, state)
        processed = await asyncio.to_thread(_process_bytes, source_bytes, updated_state)

        if action == Action.PUBLISH:
            commit = await asyncio.to_thread(STORE.publish, processed.epd_data)
            public_url = os.environ.get("PUBLIC_IMAGE_URL", "").strip()
            suffix = f"\n{public_url}" if public_url else ""
            await query.edit_message_caption(
                caption=(
                    "Imagen publicada correctamente.\n"
                    f"Commit: {commit[:12]}\n"
                    "El ESP la comprobara en su proximo ciclo."
                    f"{suffix}"
                ),
                reply_markup=None,
            )
            return

        if action in {
            Action.PAN_UP,
            Action.PAN_DOWN,
            Action.PAN_LEFT,
            Action.PAN_RIGHT,
            Action.ZOOM_IN,
            Action.ZOOM_OUT,
            Action.RESET_CROP,
        }:
            keyboard = _crop_keyboard(updated_state)
        elif action in {
            Action.BRIGHTNESS_UP,
            Action.BRIGHTNESS_DOWN,
            Action.CONTRAST_UP,
            Action.CONTRAST_DOWN,
            Action.DITHER_UP,
            Action.DITHER_DOWN,
            Action.RED_UP,
            Action.RED_DOWN,
            Action.SHARPNESS_UP,
            Action.SHARPNESS_DOWN,
            Action.RESET_TONE,
        }:
            keyboard = _tone_keyboard(updated_state)
        else:
            keyboard = _main_keyboard(updated_state)

        media = preview_photo(
            processed.preview_png,
            _caption(updated_state, processed),
        )
        await query.edit_message_media(media=media, reply_markup=keyboard)
    except Exception as error:
        LOGGER.exception("Callback processing failed")
        await query.edit_message_caption(
            caption=(
                "No pude completar la operacion. La imagen publicada anteriormente "
                f"no fue modificada.\nError: {error}"
            ),
            reply_markup=_main_keyboard(state),
        )


async def receive_manual_values(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.text is None:
        return

    prompt = message.reply_to_message
    session_url = manual_session_url(prompt)
    if session_url is None:
        return
    if not _authorized(user.id):
        await message.reply_text("No tienes permiso para modificar esta pantalla.")
        return

    try:
        session = decode_manual_session(session_url, _manual_secret())
        if session.chat_id != message.chat_id:
            raise ValueError("La solicitud pertenece a otro chat.")
        action, state = decode_callback(session.callback_data)
        if action != Action.MANUAL_VALUES:
            raise ValueError("La solicitud manual no es valida.")
    except ValueError:
        await message.reply_text(
            "Esta solicitud ya no es valida. Abre Valores manuales nuevamente."
        )
        return

    try:
        updated_state = parse_manual_values(message.text, state)
    except ValueError as error:
        await _send_manual_prompt(message, session_url, state, str(error))
        return

    try:
        source_bytes = await _download_file_id(session.file_id, context)
        processed = await asyncio.to_thread(
            _process_bytes,
            source_bytes,
            updated_state,
        )
        await context.bot.edit_message_media(
            chat_id=session.chat_id,
            message_id=session.preview_message_id,
            media=preview_photo(
                processed.preview_png,
                _caption(updated_state, processed),
            ),
            reply_markup=_tone_keyboard(updated_state),
        )
        await _delete_manual_messages(message, context)
    except Exception as error:
        LOGGER.exception("Manual value processing failed")
        await message.reply_text(f"No pude aplicar esos valores: {error}")


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    LOGGER.exception("Unhandled Telegram update", exc_info=context.error)


def _process_bytes(source_bytes: bytes, state: EditState) -> ProcessedImage:
    return process_image(load_source(source_bytes), state)


async def _download_image(
    message: Message, context: ContextTypes.DEFAULT_TYPE
) -> bytes:
    return await _download_file_id(_image_file_id(message), context)


def _image_file_id(message: Message) -> str:
    if message.photo:
        return message.photo[-1].file_id
    elif message.document and message.document.mime_type:
        if not message.document.mime_type.startswith("image/"):
            raise ValueError("El documento no es una imagen")
        return message.document.file_id
    else:
        raise ValueError("No encontre una foto en el mensaje original")


async def _download_file_id(
    file_id: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> bytes:
    telegram_file = await context.bot.get_file(file_id)
    output = BytesIO()
    await telegram_file.download_to_memory(out=output)
    return output.getvalue()


async def _send_manual_prompt(
    reply_target: Message,
    session_url: str,
    state: EditState,
    error: str | None = None,
) -> None:
    prefix = f"{error}\n\n" if error else ""
    current_values = (
        f"{state.brightness} {state.contrast} {state.dither} "
        f"{state.sharpness} {state.red_sensitivity}"
    )
    text = (
        f"{prefix}"
        "Escribe 5 numeros separados por espacios:\n"
        "brillo contraste trama nitidez rojo\n\n"
        f"Valores actuales: {current_values}\n"
        "Rangos: brillo -5..5, contraste -5..8, los demas 0..10.\n"
        "Solicitud vinculada a esta foto."
    )
    link_text = "esta foto"
    await reply_target.reply_text(
        text,
        entities=[
            MessageEntity(
                type=MessageEntity.TEXT_LINK,
                offset=text.index(link_text),
                length=len(link_text),
                url=session_url,
            )
        ],
        reply_markup=ForceReply(
            selective=True,
            input_field_placeholder=current_values,
        ),
        disable_web_page_preview=True,
    )


async def _delete_manual_messages(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message_ids = [message.message_id]
    if message.reply_to_message is not None:
        message_ids.append(message.reply_to_message.message_id)
    for message_id in message_ids:
        try:
            await context.bot.delete_message(message.chat_id, message_id)
        except TelegramError:
            LOGGER.debug("Could not delete manual input message %s", message_id)


def _original_message(message: Message | None) -> Message | None:
    if message is None:
        return None
    original = message.reply_to_message
    if original and (original.photo or original.document):
        return original
    return None


def _button(text: str, action: Action, state: EditState) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=encode_callback(action, state))


def _main_keyboard(state: EditState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_button("Publicar", Action.PUBLISH, state)],
            [
                _button("Cambiar estilo", Action.MENU_STYLE, state),
                _button("Ajustar recorte", Action.MENU_CROP, state),
            ],
            [_button("Luz y color", Action.MENU_TONE, state)],
            [_button("Cancelar", Action.CANCEL, state)],
        ]
    )


def _style_keyboard(state: EditState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_button("Foto blanco, negro y rojo", Action.STYLE_BWR, state)],
            [_button("Foto blanco y negro", Action.STYLE_BW, state)],
            [_button("Texto o logo", Action.STYLE_TEXT, state)],
            [_button("Volver", Action.BACK_MAIN, state)],
        ]
    )


def _crop_keyboard(state: EditState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_button("Arriba", Action.PAN_UP, state)],
            [
                _button("Izquierda", Action.PAN_LEFT, state),
                _button("Derecha", Action.PAN_RIGHT, state),
            ],
            [_button("Abajo", Action.PAN_DOWN, state)],
            [
                _button("Acercar", Action.ZOOM_IN, state),
                _button("Alejar", Action.ZOOM_OUT, state),
            ],
            [_button("Restablecer recorte", Action.RESET_CROP, state)],
            [_button("Volver", Action.BACK_MAIN, state)],
        ]
    )


def _tone_keyboard(state: EditState) -> InlineKeyboardMarkup:
    rows = [
        [
            _button("Menos brillo", Action.BRIGHTNESS_DOWN, state),
            _button("Mas brillo", Action.BRIGHTNESS_UP, state),
        ],
        [
            _button("Menos contraste", Action.CONTRAST_DOWN, state),
            _button("Mas contraste", Action.CONTRAST_UP, state),
        ],
        [
            _button("Menos trama", Action.DITHER_DOWN, state),
            _button("Mas trama", Action.DITHER_UP, state),
        ],
        [
            _button("Menos nitidez", Action.SHARPNESS_DOWN, state),
            _button("Mas nitidez", Action.SHARPNESS_UP, state),
        ],
        [_button("Valores manuales", Action.MANUAL_VALUES, state)],
    ]
    if state.preset != Preset.PHOTO_BW:
        rows.append(
            [
                _button("Menos rojo", Action.RED_DOWN, state),
                _button("Mas rojo", Action.RED_UP, state),
            ]
        )
    rows.extend(
        [
            [_button("Restablecer estilo", Action.RESET_TONE, state)],
            [_button("Volver", Action.BACK_MAIN, state)],
        ]
    )
    return InlineKeyboardMarkup(rows)


def _caption(state: EditState, processed: ProcessedImage) -> str:
    style = {
        Preset.PHOTO_BWR: "Foto BWR",
        Preset.PHOTO_BW: "Foto B/N",
        Preset.TEXT_LOGO: "Texto/Logo",
    }[state.preset]
    red_line = (
        f"Rojo: {state.red_sensitivity}/10, {processed.red_pixels} pixeles\n"
        if state.preset != Preset.PHOTO_BW
        else "Rojo: desactivado\n"
    )
    return (
        f"Vista previa 296x152\n"
        f"Estilo: {style}\n"
        f"Recorte: zoom {state.zoom}/10, X {state.pan_x:+d}, Y {state.pan_y:+d}\n"
        f"Brillo: {state.brightness:+d}, contraste: {state.contrast:+d}\n"
        f"Trama: {state.dither}/10, nitidez: {state.sharpness}/10\n"
        f"{red_line}"
        f"Negro: {processed.black_pixels} pixeles"
    )


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    application = Application.builder().token(_required_environment("TELEGRAM_BOT_TOKEN")).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, receive_manual_values)
    )
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, receive_image)
    )
    application.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^e1"))
    application.add_error_handler(error_handler)

    webhook_base_url = (
        os.environ.get("TELEGRAM_WEBHOOK_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or ""
    ).rstrip("/")
    if webhook_base_url:
        webhook_path = os.environ.get("TELEGRAM_WEBHOOK_PATH", "telegram")
        webhook_secret = normalize_webhook_secret(
            _required_environment("TELEGRAM_WEBHOOK_SECRET")
        )
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            url_path=webhook_path,
            webhook_url=f"{webhook_base_url}/{webhook_path}",
            secret_token=webhook_secret,
            drop_pending_updates=True,
        )
    else:
        LOGGER.warning("TELEGRAM_WEBHOOK_URL is not set; using long polling")
        application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
