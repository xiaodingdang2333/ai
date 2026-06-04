package com.qianliyan.sheetmusic;

import android.app.*;
import android.os.*;
import android.provider.OpenableColumns;
import android.graphics.*;
import android.graphics.pdf.*;
import android.net.Uri;
import android.content.*;
import android.database.Cursor;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import android.text.InputType;
import java.io.*;
import java.util.*;
import org.json.*;

public class MainActivity extends Activity {
    static final int BLUE = Color.rgb(37, 99, 235), INK = Color.rgb(24, 24, 27), PAPER = Color.rgb(255, 253, 248);
    static final int PDF_REQ = 10, IMG_REQ = 11;
    LinearLayout root, content, nav;
    ArrayList<Track> tracks = new ArrayList<>();
    ArrayList<String> setlists = new ArrayList<>(), tags = new ArrayList<>();
    Track current;
    PdfRenderer renderer;
    ParcelFileDescriptor pfd;
    int pageIndex = 0, halfMode = 0; // 0 full, 1 top, 2 bottom
    ScoreView scoreView;
    String tool = "手写";

    public void onCreate(Bundle b) {
        super.onCreate(b);
        loadState();
        if (setlists.isEmpty()) Collections.addAll(setlists, "周六婚礼演出", "练习清单", "古典独奏");
        if (tags.isEmpty()) Collections.addAll(tags, "钢琴", "婚礼", "练习中", "待练");
        showShell("乐谱库");
        showLibrary();
    }

    void showShell(String title) {
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(PAPER);
        LinearLayout top = new LinearLayout(this); top.setPadding(dp(18), dp(14), dp(18), dp(8)); top.setGravity(Gravity.CENTER_VERTICAL);
        TextView t = text(title, 24, true); top.addView(t, new LinearLayout.LayoutParams(0, -2, 1));
        root.addView(top);
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(dp(16), dp(8), dp(16), dp(8));
        root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1));
        nav = new LinearLayout(this); nav.setPadding(dp(10), dp(8), dp(10), dp(12)); nav.setGravity(Gravity.CENTER); nav.setBackgroundColor(Color.WHITE);
        addNav("乐谱库", v -> showLibrary()); addNav("Setlist", v -> showSetlist()); addNav("标签", v -> showTags()); addNav("设置", v -> showSettings());
        root.addView(nav);
        setContentView(root);
    }

    void addNav(String s, View.OnClickListener l) {
        TextView v = pill(s, false); v.setOnClickListener(l); nav.addView(v, new LinearLayout.LayoutParams(0, dp(44), 1));
    }

    void reset(String title) { showShell(title); }

    void showLibrary() {
        reset("乐谱库");
        EditText search = input("搜索曲目、作曲家、标签"); content.addView(search);
        LinearLayout actions = row(); actions.addView(button("导入PDF", v -> pickPdf()), new LinearLayout.LayoutParams(0, dp(48), 1));
        actions.addView(space(10, 1)); actions.addView(button("照片生成PDF", v -> pickImages()), new LinearLayout.LayoutParams(0, dp(48), 1));
        content.addView(actions);
        ScrollView sv = new ScrollView(this); LinearLayout list = col(); sv.addView(list); content.addView(sv, new LinearLayout.LayoutParams(-1, 0, 1));
        if (tracks.isEmpty()) {
            TextView empty = text("还没有乐谱\n点击“导入PDF”或“照片生成PDF”开始。", 18, false); empty.setGravity(Gravity.CENTER); list.addView(empty, new LinearLayout.LayoutParams(-1, dp(260)));
        } else {
            for (Track tr : tracks) list.addView(trackRow(tr));
        }
    }

    View trackRow(Track tr) {
        LinearLayout card = card(); card.setOnClickListener(v -> openTrack(tr));
        TextView title = text(tr.title, 18, true); card.addView(title);
        card.addView(text((tr.author.isEmpty() ? "未知作者" : tr.author) + " · " + tr.pages + "页", 13, false));
        LinearLayout chips = row(); for (String tag : tr.tags) chips.addView(chip(tag)); card.addView(chips);
        LinearLayout ops = row(); ops.setGravity(Gravity.RIGHT);
        ops.addView(small("标签", v -> editTrackTags(tr))); ops.addView(small("加入Setlist", v -> addToSetlist(tr)));
        card.addView(ops);
        return card;
    }

    void showSetlist() {
        reset("Setlist");
        content.addView(button("+ 新建曲单", v -> prompt("新建曲单", "", s -> { if (!s.isEmpty()) setlists.add(s); saveState(); showSetlist(); })), new LinearLayout.LayoutParams(-1, dp(50)));
        for (String s : setlists) {
            LinearLayout c = card(); c.addView(text(s, 18, true));
            int count = 0; for (Track t : tracks) if (s.equals(t.setlist)) count++;
            c.addView(text(count + " 首曲目", 13, false)); content.addView(c);
        }
    }

    void showTags() {
        reset("标签");
        content.addView(button("+ 新建标签", v -> prompt("新建标签", "", s -> { if (!s.isEmpty()) tags.add(s); saveState(); showTags(); })), new LinearLayout.LayoutParams(-1, dp(50)));
        LinearLayout wrap = col(); content.addView(wrap);
        for (String tag : tags) {
            int count = 0; for (Track t : tracks) if (t.tags.contains(tag)) count++;
            LinearLayout c = card(); c.addView(text(tag, 18, true)); c.addView(text(count + " 首曲目", 13, false)); wrap.addView(c);
        }
    }

    void showSettings() {
        reset("设置");
        LinearLayout c = card();
        c.addView(text("乐谱助手", 20, true));
        c.addView(text("Android 13+ · PDF 乐谱管理 · 批注 · 半页翻页 · 照片生成PDF", 14, false));
        content.addView(c);
    }

    void openTrack(Track tr) {
        current = tr; pageIndex = Math.max(0, Math.min(tr.lastPage, tr.pages - 1)); halfMode = 0;
        try {
            closePdf();
            pfd = ParcelFileDescriptor.open(new File(tr.path), ParcelFileDescriptor.MODE_READ_ONLY);
            renderer = new PdfRenderer(pfd);
            showReader();
        } catch (Exception e) { toast("无法打开PDF：" + e.getMessage()); }
    }

    void showReader() {
        reset(current.title);
        LinearLayout bar = row();
        bar.addView(button("批注", v -> showAnnotTools()), new LinearLayout.LayoutParams(0, dp(44), 1));
        bar.addView(button("标签", v -> editTrackTags(current)), new LinearLayout.LayoutParams(0, dp(44), 1));
        bar.addView(button("更多", v -> toast("第一版暂未开放更多功能")), new LinearLayout.LayoutParams(0, dp(44), 1));
        content.addView(bar);
        TextView pageInfo = text((pageIndex + 1) + " / " + current.pages, 14, false); pageInfo.setGravity(Gravity.CENTER); content.addView(pageInfo);
        scoreView = new ScoreView(this); content.addView(scoreView, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout turn = row();
        turn.addView(button("上一页", v -> { if (pageIndex > 0) { pageIndex--; halfMode = 0; showReader(); } }), new LinearLayout.LayoutParams(0, dp(48), 1));
        turn.addView(button("上半页", v -> { halfMode = 1; scoreView.invalidate(); }), new LinearLayout.LayoutParams(0, dp(48), 1));
        turn.addView(button("下半页", v -> { halfMode = 2; scoreView.invalidate(); }), new LinearLayout.LayoutParams(0, dp(48), 1));
        turn.addView(button("下一页", v -> { if (pageIndex < current.pages - 1) { pageIndex++; halfMode = 0; showReader(); } }), new LinearLayout.LayoutParams(0, dp(48), 1));
        content.addView(turn);
        current.lastPage = pageIndex; saveState();
    }

    void showAnnotTools() {
        final String[] tools = {"手写", "文字", "高亮", "橡皮", "撤销"};
        new AlertDialog.Builder(this).setTitle("批注").setItems(tools, (d, which) -> {
            if ("撤销".equals(tools[which])) { ArrayList<Anno> a = annos(); if (!a.isEmpty()) a.remove(a.size() - 1); saveState(); scoreView.invalidate(); }
            else { tool = tools[which]; toast("当前工具：" + tool); }
        }).show();
    }

    ArrayList<Anno> annos() {
        String key = String.valueOf(pageIndex);
        if (!current.annos.containsKey(key)) current.annos.put(key, new ArrayList<>());
        return current.annos.get(key);
    }

    void pickPdf() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT); i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("application/pdf"); startActivityForResult(i, PDF_REQ);
    }

    void pickImages() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT); i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("image/*"); i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true); startActivityForResult(i, IMG_REQ);
    }

    public void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (res != RESULT_OK || data == null) return;
        try {
            if (req == PDF_REQ) importPdf(data.getData());
            if (req == IMG_REQ) importImages(data);
        } catch (Exception e) { toast("导入失败：" + e.getMessage()); }
    }

    void importPdf(Uri uri) throws Exception {
        String name = displayName(uri); if (!name.toLowerCase().endsWith(".pdf")) name += ".pdf";
        File out = uniqueFile(name); copyUri(uri, out);
        int pages = countPages(out);
        Track t = new Track(); t.title = name.replaceFirst("(?i)\\.pdf$", ""); t.path = out.getAbsolutePath(); t.pages = pages; tracks.add(t);
        saveState(); showLibrary();
    }

    void importImages(Intent data) throws Exception {
        ArrayList<Uri> uris = new ArrayList<>();
        if (data.getClipData() != null) for (int i = 0; i < data.getClipData().getItemCount(); i++) uris.add(data.getClipData().getItemAt(i).getUri());
        else if (data.getData() != null) uris.add(data.getData());
        if (uris.isEmpty()) return;
        File out = uniqueFile("照片乐谱_" + System.currentTimeMillis() + ".pdf");
        PdfDocument doc = new PdfDocument();
        int pageNo = 1;
        for (Uri u : uris) {
            Bitmap bmp = loadBitmap(u);
            PdfDocument.PageInfo info = new PdfDocument.PageInfo.Builder(1240, 1754, pageNo++).create();
            PdfDocument.Page p = doc.startPage(info);
            Rect dst = fitRect(bmp.getWidth(), bmp.getHeight(), 1240, 1754);
            p.getCanvas().drawColor(Color.WHITE);
            p.getCanvas().drawBitmap(bmp, null, dst, null);
            doc.finishPage(p);
            bmp.recycle();
        }
        FileOutputStream fos = new FileOutputStream(out); doc.writeTo(fos); fos.close(); doc.close();
        Track t = new Track(); t.title = out.getName().replace(".pdf", ""); t.path = out.getAbsolutePath(); t.pages = pageNo - 1; tracks.add(t);
        saveState(); showLibrary();
    }

    class ScoreView extends View {
        Bitmap pageBmp; Paint p = new Paint(Paint.ANTI_ALIAS_FLAG); ArrayList<PointF> temp = new ArrayList<>();
        ScoreView(Context c) { super(c); setBackgroundColor(Color.rgb(250, 247, 238)); }
        protected void onDraw(Canvas c) {
            super.onDraw(c);
            if (renderer == null) return;
            try {
                if (pageBmp == null) {
                    PdfRenderer.Page page = renderer.openPage(pageIndex);
                    pageBmp = Bitmap.createBitmap(page.getWidth() * 2, page.getHeight() * 2, Bitmap.Config.ARGB_8888);
                    pageBmp.eraseColor(Color.WHITE); page.render(pageBmp, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY); page.close();
                }
                Rect src = new Rect(0, 0, pageBmp.getWidth(), pageBmp.getHeight());
                if (halfMode == 1) src.bottom = pageBmp.getHeight() / 2;
                if (halfMode == 2) src.top = pageBmp.getHeight() / 2;
                Rect dst = fitRect(src.width(), src.height(), getWidth(), getHeight());
                c.drawBitmap(pageBmp, src, dst, null);
                float sx = dst.width() / (float) src.width(), sy = dst.height() / (float) src.height();
                c.save(); c.clipRect(dst); c.translate(dst.left, dst.top - src.top * sy); c.scale(sx, sy);
                for (Anno a : annos()) a.draw(c);
                drawTemp(c); c.restore();
            } catch (Exception e) { c.drawText("PDF渲染失败", dp(30), dp(60), p); }
        }
        public boolean onTouchEvent(android.view.MotionEvent e) {
            if ("文字".equals(tool) && e.getAction() == MotionEvent.ACTION_UP) {
                prompt("添加文字批注", "", s -> { if (!s.isEmpty()) { Anno a = new Anno("text"); a.text = s; a.points.add(new PointF(e.getX(), e.getY())); annos().add(a); saveState(); invalidate(); }});
                return true;
            }
            if ("橡皮".equals(tool) && e.getAction() == MotionEvent.ACTION_UP) { ArrayList<Anno> as = annos(); if (!as.isEmpty()) as.remove(as.size() - 1); saveState(); invalidate(); return true; }
            if (e.getAction() == MotionEvent.ACTION_DOWN) temp.clear();
            temp.add(new PointF(e.getX(), e.getY()));
            if (e.getAction() == MotionEvent.ACTION_UP) { Anno a = new Anno("高亮".equals(tool) ? "highlight" : "pen"); a.points.addAll(temp); annos().add(a); temp.clear(); saveState(); }
            invalidate(); return true;
        }
        void drawTemp(Canvas c) { if (temp.size() < 2) return; Anno a = new Anno("高亮".equals(tool) ? "highlight" : "pen"); a.points.addAll(temp); a.draw(c); }
    }

    static class Track {
        String title = "", author = "", path = "", setlist = ""; int pages = 1, lastPage = 0;
        ArrayList<String> tags = new ArrayList<>(); HashMap<String, ArrayList<Anno>> annos = new HashMap<>();
    }

    static class Anno {
        String type, text = ""; ArrayList<PointF> points = new ArrayList<>();
        Anno(String t) { type = t; }
        void draw(Canvas c) {
            Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
            if ("highlight".equals(type)) { p.setColor(Color.argb(110, 255, 214, 10)); p.setStrokeWidth(26); }
            else { p.setColor("text".equals(type) ? Color.rgb(185, 28, 28) : INK); p.setStrokeWidth(6); }
            p.setStyle(Paint.Style.STROKE); p.setStrokeCap(Paint.Cap.ROUND); p.setStrokeJoin(Paint.Join.ROUND);
            if ("text".equals(type) && !points.isEmpty()) { p.setStyle(Paint.Style.FILL); p.setTextSize(42); c.drawText(text, points.get(0).x, points.get(0).y, p); return; }
            for (int i = 1; i < points.size(); i++) c.drawLine(points.get(i-1).x, points.get(i-1).y, points.get(i).x, points.get(i).y, p);
        }
    }

    void editTrackTags(Track t) {
        String[] arr = tags.toArray(new String[0]); boolean[] checked = new boolean[arr.length];
        for (int i = 0; i < arr.length; i++) checked[i] = t.tags.contains(arr[i]);
        new AlertDialog.Builder(this).setTitle("标签").setMultiChoiceItems(arr, checked, (d, w, c) -> {
            if (c && !t.tags.contains(arr[w])) t.tags.add(arr[w]); if (!c) t.tags.remove(arr[w]);
        }).setPositiveButton("保存", (d,w)-> { saveState(); showLibrary(); }).show();
    }

    void addToSetlist(Track t) {
        String[] arr = setlists.toArray(new String[0]);
        new AlertDialog.Builder(this).setTitle("加入Setlist").setItems(arr, (d, w) -> { t.setlist = arr[w]; saveState(); toast("已加入：" + arr[w]); }).show();
    }

    TextView text(String s, int sp, boolean bold) { TextView v = new TextView(this); v.setText(s); v.setTextSize(sp); v.setTextColor(INK); v.setPadding(0, dp(4), 0, dp(4)); if (bold) v.setTypeface(Typeface.DEFAULT_BOLD); return v; }
    TextView pill(String s, boolean active) { TextView v = text(s, 14, active); v.setGravity(Gravity.CENTER); v.setBackground(round(active ? BLUE : Color.TRANSPARENT, dp(18))); v.setTextColor(active ? Color.WHITE : Color.rgb(82,82,91)); return v; }
    TextView chip(String s) { TextView v = text(s, 12, false); v.setTextColor(BLUE); v.setPadding(dp(10), dp(5), dp(10), dp(5)); v.setBackground(round(Color.rgb(239,246,255), dp(14))); return v; }
    TextView small(String s, View.OnClickListener l) { TextView v = chip(s); v.setOnClickListener(l); return v; }
    Button button(String s, View.OnClickListener l) { Button b = new Button(this); b.setText(s); b.setTextColor(Color.WHITE); b.setBackground(round(BLUE, dp(12))); b.setOnClickListener(l); return b; }
    EditText input(String hint) { EditText e = new EditText(this); e.setHint(hint); e.setSingleLine(true); e.setBackground(round(Color.WHITE, dp(14))); e.setPadding(dp(14), 0, dp(14), 0); return e; }
    LinearLayout row() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.HORIZONTAL); l.setGravity(Gravity.CENTER_VERTICAL); l.setPadding(0, dp(6), 0, dp(6)); return l; }
    LinearLayout col() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); return l; }
    LinearLayout card() { LinearLayout l = col(); l.setPadding(dp(16), dp(14), dp(16), dp(14)); l.setBackground(round(Color.WHITE, dp(16))); LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2); lp.setMargins(0, 0, 0, dp(10)); l.setLayoutParams(lp); return l; }
    Space space(int w, int h) { Space s = new Space(this); s.setLayoutParams(new LinearLayout.LayoutParams(dp(w), dp(h))); return s; }
    android.graphics.drawable.GradientDrawable round(int color, int r) { android.graphics.drawable.GradientDrawable g = new android.graphics.drawable.GradientDrawable(); g.setColor(color); g.setCornerRadius(r); return g; }
    int dp(int v) { return (int)(v * getResources().getDisplayMetrics().density + .5f); }
    void toast(String s) { Toast.makeText(this, s, Toast.LENGTH_SHORT).show(); }

    interface Done { void ok(String s); }
    void prompt(String title, String value, Done done) {
        EditText e = new EditText(this); e.setText(value); e.setInputType(InputType.TYPE_CLASS_TEXT); e.setSelectAllOnFocus(true);
        new AlertDialog.Builder(this).setTitle(title).setView(e).setPositiveButton("确定", (d,w)->done.ok(e.getText().toString().trim())).setNegativeButton("取消", null).show();
    }

    File uniqueFile(String name) { File dir = new File(getFilesDir(), "scores"); dir.mkdirs(); File f = new File(dir, name); int i = 1; while (f.exists()) f = new File(dir, name.replaceFirst("(\\.pdf)?$", "_" + (i++) + ".pdf")); return f; }
    void copyUri(Uri uri, File out) throws Exception { InputStream in = getContentResolver().openInputStream(uri); FileOutputStream fos = new FileOutputStream(out); byte[] buf = new byte[8192]; int n; while ((n = in.read(buf)) > 0) fos.write(buf,0,n); in.close(); fos.close(); }
    String displayName(Uri uri) { try (Cursor c = getContentResolver().query(uri, null, null, null, null)) { if (c != null && c.moveToFirst()) { int i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME); if (i >= 0) return c.getString(i); } } catch(Exception ignored){} return "导入乐谱.pdf"; }
    int countPages(File f) throws Exception { ParcelFileDescriptor fd = ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY); PdfRenderer r = new PdfRenderer(fd); int c = r.getPageCount(); r.close(); fd.close(); return c; }
    Bitmap loadBitmap(Uri uri) throws Exception { return ImageDecoder.decodeBitmap(ImageDecoder.createSource(getContentResolver(), uri)); }
    Rect fitRect(int sw, int sh, int dw, int dh) { float s = Math.min(dw/(float)sw, dh/(float)sh); int w=(int)(sw*s), h=(int)(sh*s); int l=(dw-w)/2, t=(dh-h)/2; return new Rect(l,t,l+w,t+h); }
    void closePdf() { try { if (renderer != null) renderer.close(); if (pfd != null) pfd.close(); } catch(Exception ignored){} renderer = null; pfd = null; }

    void saveState() {
        try {
            JSONArray arr = new JSONArray();
            for (Track t : tracks) {
                JSONObject o = new JSONObject(); o.put("title",t.title).put("author",t.author).put("path",t.path).put("pages",t.pages).put("last",t.lastPage).put("setlist",t.setlist);
                o.put("tags", new JSONArray(t.tags)); JSONObject ao = new JSONObject();
                for (String k : t.annos.keySet()) { JSONArray aa = new JSONArray(); for (Anno a : t.annos.get(k)) { JSONObject x = new JSONObject(); x.put("type",a.type).put("text",a.text); JSONArray pts = new JSONArray(); for(PointF p:a.points) pts.put(new JSONArray().put(p.x).put(p.y)); x.put("pts",pts); aa.put(x); } ao.put(k,aa); }
                o.put("annos", ao); arr.put(o);
            }
            getPreferences(0).edit().putString("tracks", arr.toString()).putString("setlists", new JSONArray(setlists).toString()).putString("tags", new JSONArray(tags).toString()).apply();
        } catch(Exception ignored){}
    }

    void loadState() {
        try {
            SharedPreferences sp = getPreferences(0);
            JSONArray arr = new JSONArray(sp.getString("tracks","[]"));
            for (int i=0;i<arr.length();i++) { JSONObject o=arr.getJSONObject(i); Track t=new Track(); t.title=o.optString("title"); t.author=o.optString("author"); t.path=o.optString("path"); t.pages=o.optInt("pages",1); t.lastPage=o.optInt("last"); t.setlist=o.optString("setlist"); JSONArray ta=o.optJSONArray("tags"); if(ta!=null) for(int j=0;j<ta.length();j++) t.tags.add(ta.getString(j)); JSONObject ao=o.optJSONObject("annos"); if(ao!=null){ Iterator<String> it=ao.keys(); while(it.hasNext()){ String k=it.next(); JSONArray aa=ao.getJSONArray(k); ArrayList<Anno> list=new ArrayList<>(); for(int j=0;j<aa.length();j++){ JSONObject x=aa.getJSONObject(j); Anno a=new Anno(x.optString("type")); a.text=x.optString("text"); JSONArray pts=x.getJSONArray("pts"); for(int n=0;n<pts.length();n++){ JSONArray p=pts.getJSONArray(n); a.points.add(new PointF((float)p.getDouble(0),(float)p.getDouble(1))); } list.add(a);} t.annos.put(k,list);} } tracks.add(t); }
            JSONArray sl = new JSONArray(sp.getString("setlists","[]")); for(int i=0;i<sl.length();i++) setlists.add(sl.getString(i));
            JSONArray tg = new JSONArray(sp.getString("tags","[]")); for(int i=0;i<tg.length();i++) tags.add(tg.getString(i));
        } catch(Exception ignored){}
    }
}
