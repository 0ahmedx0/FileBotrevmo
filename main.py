import asyncio
import os
from dotenv import load_dotenv
from pyrogram import Client, errors
from pyrogram.types import InputMediaPhoto, InputMediaVideo, InputMediaDocument

# تحميل إعدادات البيئة من ملف .env
load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
SESSION = os.getenv("SESSION")

# معرفات القنوات وروابط الدعوة
SOURCE_INVITE = os.getenv("CHANNEL_ID", "")
DEST_INVITE = os.getenv("CHANNEL_ID_LOG", "")

# معرف أول وآخر رسالة لتحديد النطاق يدويًا
FIRST_MSG_ID = int(os.getenv("FIRST_MSG_ID", "1"))
LAST_MESSAGE_ID = int(os.getenv("LAST_MESSAGE_ID", "14356"))  # حدد آخر رسالة هنا

async def collect_albums(client: Client, chat_id: int, first_msg_id: int, last_msg_id: int):
    """
    يجمع الرسائل التي تحتوي على media_group_id من القناة بدءًا من first_msg_id وحتى last_msg_id.
    يتم جمع البيانات على دفعات من 500 رسالة لضمان الكفاءة.
    """
    albums = {}
    offset_id = first_msg_id - 1  # نبدأ من أول رسالة محددة
    while True:
        messages_batch = []
        async for message in client.get_chat_history(chat_id, offset_id=offset_id, limit=500, reverse=True):
            if message.id > last_msg_id:
                continue  # تجاوز الرسائل الأحدث من المطلوب
            if message.id < first_msg_id:
                break  # توقف عند الوصول إلى الرسالة الأقدم المحددة
            messages_batch.append(message)
            if message.media_group_id:
                albums.setdefault(message.media_group_id, []).append(message)

        if not messages_batch:
            break  # توقف عند عدم وجود رسائل أخرى للمعالجة
        
        offset_id = messages_batch[-1].id  # تحديث نقطة البداية للدورة التالية
    
    return albums

async def transfer_album(client: Client, source_chat_id: int, dest_chat_id: int, album_messages: list):
    """
    ينقل الألبومات من القناة المصدر إلى القناة الوجهة بالترتيب الزمني الصحيح.
    """
    album_messages_sorted = sorted(album_messages, key=lambda m: m.id)  # ترتيب تصاعدي
    media_group = []
    
    for index, message in enumerate(album_messages_sorted):
        caption = message.caption if index == 0 else ""
        if message.photo:
            media_group.append(InputMediaPhoto(media=message.photo.file_id, caption=caption))
        elif message.video:
            media_group.append(InputMediaVideo(media=message.video.file_id, caption=caption, supports_streaming=True))
        elif message.document:
            if message.document.mime_type and message.document.mime_type.startswith("video/"):
                media_group.append(InputMediaVideo(media=message.document.file_id, caption=caption, supports_streaming=True))
            else:
                media_group.append(InputMediaDocument(media=message.document.file_id, caption=caption))
    
    if not media_group:
        print(f"⚠️ لا توجد وسائط في الألبوم {album_messages_sorted[0].id}. يتم تخطيه.")
        return

    try:
        await client.send_media_group(chat_id=dest_chat_id, media=media_group)
        print(f"✅ تم إرسال ألبوم الرسائل {[msg.id for msg in album_messages_sorted]} إلى القناة الوجهة")
    except errors.FloodWait as e:
        print(f"⏳ تجاوز الحد: الانتظار {e.value} ثانية...")
        await asyncio.sleep(e.value + 1)
        await client.send_media_group(chat_id=dest_chat_id, media=media_group)
    except Exception as ex:
        print(f"⚠️ خطأ أثناء إرسال الألبوم {[msg.id for msg in album_messages_sorted]}: {ex}")

async def process_albums(client: Client, source_invite: str, dest_invite: str):
    """
    ينضم إلى القناتين، يجمع الألبومات من القناة المصدر، ويرسلها إلى القناة الوجهة.
    """
    print("🔍 جاري تجميع الألبومات...")

    # الانضمام إلى القناة المصدر
    try:
        source_chat = await client.join_chat(source_invite)
        print("✅ تم الانضمام للقناة المصدر")
    except errors.UserAlreadyParticipant:
        source_chat = await client.get_chat(source_invite)
        print("✅ الحساب مشارك مسبقاً في القناة المصدر")
    except Exception as e:
        print(f"⚠️ لم يتم الانضمام للقناة المصدر: {e}")
        return

    # الانضمام إلى القناة الوجهة
    try:
        dest_chat = await client.join_chat(dest_invite)
        print("✅ تم الانضمام للقناة الوجهة")
    except errors.UserAlreadyParticipant:
        dest_chat = await client.get_chat(dest_invite)
        print("✅ الحساب مشارك مسبقاً في القناة الوجهة")
    except errors.FloodWait as e:
        print(f"⚠️ Flood Wait: الانتظار {e.value} ثانية قبل إعادة المحاولة.")
        await asyncio.sleep(e.value + 5)
        dest_chat = await client.join_chat(dest_invite)
    except Exception as e:
        print(f"⚠️ لم يتم الانضمام للقناة الوجهة: {e}")
        return

    albums = await collect_albums(client, source_chat.id, FIRST_MSG_ID, LAST_MESSAGE_ID)
    print(f"تم العثور على {len(albums)} ألبوم.")

    # ترتيب الألبومات حسب أقدم رسالة في كل ألبوم
    sorted_albums = sorted(albums.items(), key=lambda item: min(msg.id for msg in item[1]))

    for media_group_id, messages in sorted_albums:
        print(f"📂 ألبوم {media_group_id} يحتوي على الرسائل: {[msg.id for msg in messages]}")
        await transfer_album(client, source_chat.id, dest_chat.id, messages)
        await asyncio.sleep(10)  # تأخير 10 ثوانٍ بين كل ألبوم

async def main():
    async with Client(
        "my_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION
    ) as client:
        print("🚀 العميل متصل بنجاح.")
        await process_albums(client, SOURCE_INVITE, DEST_INVITE)

if __name__ == "__main__":
    print("🔹 بدء تشغيل البوت...")
    asyncio.run(main())
