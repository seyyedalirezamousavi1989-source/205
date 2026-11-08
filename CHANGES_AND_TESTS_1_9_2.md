# تغییرات و آزمون‌ها — 1.9.2

## تغییرات
1. toolchains.py (جدید): نوع پروژه و وظایف ثابت Flutter/Gradle/Node، فایل‌های .vscode.
2. system_tools.py: `kind` در پروژه، `toolchain_run`، `editor_setup`، `editor_extension`، `open_in_editor` با فایل/خط، گزارش ابزارها در `check_environment`.
3. project_analysis.py: snapshot و `analyze_generic` برای dart/gradle/node.
4. coding_agent.py: تعریف ابزارهای فشرده + `select_tools`، `kind`/`stack_reason` در طرح، پرامپت‌های فشرده، نتیجهٔ ابزار فشرده، حذف محتوای قدیمی فایل‌ها از تاریخچه.
5. server.py / models_catalog.py: جایگزینی خودکار مدل بدون tool-calling (`pick_coding_model`)، رزرو کوچک‌تر برای تعریف ابزارها.

## اندازهٔ context (نویسه)
- تعریف همهٔ ابزارها: ۱۲٬۳۹۷ → ۶٬۷۸۶ (با ۵ ابزار جدید)؛ ارسال‌شده در عمل: پروژهٔ pygame ≈ ۳٬۲۵۴، Flutter ≈ ۲٬۶۵۵.
- پرامپت اجرا+پایه: ۲٬۳۱۳ → ۱٬۷۵۰؛ پرامپت طرح‌ساز: ۲٬۴۴۳ → ۲٬۰۷۰ (با فهرست ابزارها و قاعدهٔ انتخاب بستر).

## آزمون
مجموعهٔ کامل (شامل `test_programming_stacks.py` با Flutter/VS Code جعلی، Node واقعی، اندازهٔ context، انتخاب مدل): نتیجه در پایان همین فایل/پیام گزارش شد.

## راستی‌آزمایی‌نشده
Flutter و Gradle واقعی، Docker daemon، Ollama و مدل بینایی واقعی، مسیرهای واقعی ویندوز، VS Code واقعی (فقط اسکریپت جعلی `code`).
همهٔ ۱۴۷ آزمون موفق (۱ رد‌شده: آزمون‌های ابزار واقعی با متغیر محیطی).
