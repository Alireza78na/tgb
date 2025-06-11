# Telegram FileBot

رباتی برای مدیریت و به اشتراک‌گذاری فایل‌ها در تلگرام به همراه یک بک‌اند نوشته‌شده با FastAPI.

## 💾 نصب و اجرای پروژه

### پیش‌نیازها
1. **نصب Git**
   ```bash
   sudo apt update
   sudo apt install git -y
   ```
2. **نصب Docker و Docker Compose**
   ```bash
   sudo apt install docker.io docker-compose-v2 -y
   sudo systemctl enable --now docker
   ```
3. برای اجرای محلی نیاز است Python 3.11 نصب شده باشد.

### راه‌اندازی خودکار
اسکریپت `setup.sh` تمامی پیش‌نیازها را نصب کرده و سرویس‌ها را اجرا می‌کند. پس از کلون مخزن کافی است دستور زیر را اجرا کنید:
```bash
sudo bash setup.sh
```
در هنگام اجرا مقادیر مورد نیاز مانند توکن ربات و دامنه دانلود از شما پرسیده می‌شود و پس از اتمام، ربات و وب‌سرویس فعال خواهند شد.

### راه‌اندازی سریع با Docker
1. ابتدا مخزن را کلون کنید:
   ```bash
   git clone <آدرس-مخزن>
   cd telegram_filebot_full
   ```
2. فایل `.env` در ریشه پروژه بسازید و مقادیر زیر را وارد کنید یا از اسکریپت `setup.sh` استفاده کنید:
   ```env
   BOT_TOKEN=<توکن ربات تلگرام>
   # آدرس سرویس بک‌اند. در محیط Docker به صورت پیش‌فرض کانتینر `bot`
   # از طریق نام سرویس `backend` به وب‌سرویس دسترسی دارد.
   API_BASE_URL=http://backend:8000
   DOWNLOAD_DOMAIN=<دامنه یا IP سرور>
   ADMIN_IDS=<شناسه عددی ادمین‌ها با کاما>
  ADMIN_API_TOKEN=<توکن مخصوص ادمین>
   SUBSCRIPTION_REMINDER_DAYS=3
   REQUIRED_CHANNEL=<آیدی عددی یا یوزرنیم کانال الزامی>
   API_ID=<api id>
   API_HASH=<api hash>
   ```
   مقدار `DOWNLOAD_DOMAIN` باید به دامنه‌ای که Nginx روی آن سرویس می‌دهد اشاره کند.
3. در صورت نیاز فایل `app/settings.json` را نیز ویرایش کنید.
4. اجرای سرویس‌ها:
   ```bash
   docker compose up --build -d
   ```
5. برای مشاهده لاگ‌ها:
   ```bash
   docker compose logs -f
   ```
   بعد از بالا آمدن کانتینرها، ربات آماده استفاده است.

### اجرای محلی
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
python app/bot.py
```

متغیرهای محیطی مهم:
- `BOT_TOKEN`: توکن ربات تلگرام
- `API_BASE_URL`: آدرس API بک‌اند برای ربات
  در حالت استفاده از Docker Compose مقدار پیشنهادی `http://backend:8000` است.
- `DOWNLOAD_DOMAIN`: دامنه‌ای که به کاربر برای دانلود نشان داده می‌شود
- `SUBSCRIPTION_REMINDER_DAYS`: تعداد روزهای مانده به انقضای اشتراک که یادآوری ارسال می‌شود
- `REQUIRED_CHANNEL`: شناسه یا یوزرنیم کانالی که عضویت در آن برای استفاده از ربات الزامی است
- `API_ID` و `API_HASH`: مقادیر لازم برای استفاده از API تلگرام
مقدار `DOWNLOAD_DOMAIN` باید به دامنه‌ای که Nginx روی آن در حال سرویس‌دهی است اشاره کند.

## 🔐 احراز هویت ادمین
همه routeهای `/admin/` نیازمند هدر احراز هویت Bearer هستند:
```
Authorization: Bearer <توکن ادمین>
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

## 🖥️ پنل وب ادمین
آدرس `/admin/panel` صفحه‌ای برای مشاهده لحظه‌ای مصرف منابع سرور و ویرایش تنظیمات موجود در `settings.json` است.

## 🧪 تست‌ها
به زودی اضافه می‌شود...
