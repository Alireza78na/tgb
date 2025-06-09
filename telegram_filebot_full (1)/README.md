# Telegram FileBot

## 💾 نصب و اجرای پروژه

### اجرای محلی
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
python app/bot.py
```

متغیرهای محیطی مهم:
- `BOT_TOKEN`: توکن ربات تلگرام
- `API_BASE_URL`: آدرس API بک‌اند برای ربات
- `DOWNLOAD_DOMAIN`: دامنه‌ای که به کاربر برای دانلود نشان داده می‌شود
- `SUBSCRIPTION_REMINDER_DAYS`: تعداد روزهای مانده به انقضای اشتراک که یادآوری ارسال می‌شود

### اجرای با Docker
```bash
docker-compose up --build
```

## 🔐 احراز هویت ادمین
همه routeهای `/admin/` نیازمند header زیر هستند:
```
X-Admin-Token: SuperSecretAdminToken123
```

## 📦 ساختار
- `app/main.py`: اجرای FastAPI
- `app/bot.py`: اجرای ربات تلگرام
- `app/services/cleanup.py`: پاک‌سازی فایل‌های منقضی
- `app/services/subscription_reminder.py`: ارسال یادآوری اتمام اشتراک
  (قابل اجرا به صورت دوره‌ای برای اطلاع‌رسانی به کاربران)

## 📑 اندپوینت‌های جدید
- `POST /file/upload` بارگذاری متادیتای فایل. نیازمند هدر `X-User-Id`.
- `POST /file/upload_link` دانلود فایل از لینک و ثبت آن.
- `GET /file/list` دریافت لیست فایل‌های کاربر.
- `DELETE /file/delete/{file_id}` حذف فایل متعلق به کاربر.
- `POST /file/regenerate/{file_id}` تولید لینک دانلود جدید برای فایل.
- `POST /admin/user/block/{user_id}` مسدود کردن کاربر
- `POST /admin/user/unblock/{user_id}` رفع مسدودی کاربر
- `GET /admin/users` فهرست کاربران با امکان جستجو
- `GET /admin/files` فهرست فایل‌ها با امکان جستجو

## 🤖 دستورات ربات
- `/files` نمایش لیست فایل‌های شما
- `/delete <file_id>` حذف فایل با شناسه داده شده
- `/uploadlink <URL>` دانلود فایل از لینک
- `/mysub` نمایش اطلاعات اشتراک شما
- `/myid` دریافت آیدی عددی شما
- `/pausebot` توقف موقت ربات (ادمین)
- `/resumebot` ادامه کار ربات (ادمین)
- `/broadcast <msg>` ارسال پیام همگانی (ادمین)
- `/cancelall` لغو تمام پردازش‌ها (ادمین)
- `/admin` نمایش پنل مدیریت با دکمه‌های شیشه‌ای (ادمین)
همچنین با دکمه‌های شیشه‌ای می‌توانید لینک جدید بسازید یا فایل را حذف کنید.

## 🧪 تست‌ها
به زودی اضافه می‌شود...
