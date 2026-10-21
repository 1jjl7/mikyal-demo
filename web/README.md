# مكيال: الواجهة (صفحة ثابتة)

صفحة HTML + JS بدون سيرفر. تقرأ مخرجات المحرك من `data.js`.

## تحديث البيانات
```bash
cd engine
python make_sim.py              # أو حط بيانات بنده في مجلد البيانات
python mikyal.py
python backtest.py --tradeoff
python export_web.py            # يكتب web/data.js و web/data/*.csv ويحدّث رقم النسخة
```

## التشغيل محليًا (لابتوب العرض)
- افتح `web/index.html` مباشرة في المتصفح. يشتغل بدون إنترنت، بس الخط يرجع لخط النظام.
- أو: `python -m http.server 8765 --directory web` ثم افتح `http://localhost:8765`.

## النشر (GitHub Pages)
ارفع محتوى مجلد `web/` لمستودع، وفعّل Pages من `Settings → Pages → Deploy from branch`.
بعد كل `export_web.py` ارفع `data.js` و`index.html` (رقم النسخة يجبر الجوالات تجيب البيانات الجديدة).

## الملفات
| الملف | وش فيه |
|---|---|
| `index.html` | الهيكل: 3 تبويبات + شريط المحاكاة |
| `style.css` | الألوان (فاتح/داكن)، RTL، الجوال |
| `app.js` | كل الرسم والمنطق. ما يخترع أي رقم: كل شي من `data.js` |
| `data.js` | **مولَّد**، لا تعدّله يدويًا |
