import tkinter as tk
import re
from datetime import datetime
from decimal import Decimal
from tkinter import ttk, messagebox, simpledialog, filedialog
import csv
from .database import Database
from .scheduling import parse_schedule, parse_multi_schedule, format_schedule_list
from . import services

original_showerror = messagebox.showerror
def custom_showerror(title, message, **kwargs):
    msg = str(message)
    # Friendly MySQL error translations
    if "1062" in msg and "Duplicate entry" in msg:
        msg = "Dữ liệu này đã tồn tại (trùng mã). Vui lòng kiểm tra lại."
    elif "1451" in msg and "a foreign key constraint fails" in msg:
        msg = "Không thể xóa dữ liệu này vì đang có dữ liệu khác liên kết với nó."
    elif "1452" in msg and "a foreign key constraint fails" in msg:
        msg = "Dữ liệu tham chiếu không tồn tại."
    elif "2003" in msg and "Can't connect" in msg:
        msg = "Không thể kết nối đến cơ sở dữ liệu. Vui lòng kiểm tra MySQL server."
    elif "Access denied" in msg:
        msg = "Sai tên đăng nhập hoặc mật khẩu MySQL. Vui lòng kiểm tra cấu hình kết nối."
    else:
        # Fallback for other unrecognized errors
        if any(keyword in msg.lower() for keyword in ["error", "exception", "failed"]):
            msg = f"Lỗi hệ thống: {msg}"
            
    # Standardise titles to Vietnamese
    if title in ("Error", "Database Error", "Lỗi kết nối", "Không thể lưu điểm") or title.startswith("Error"):
        title = "Lỗi"
    elif title == "Success":
        title = "Thành công"
    original_showerror(title, msg, **kwargs)

messagebox.showerror = custom_showerror

original_showinfo = messagebox.showinfo
def custom_showinfo(title, message, **kwargs):
    if title in ("Success", "Saved", "Info") or title.startswith("Success"):
        title = "Thành công" if title in ("Success", "Saved") else "Thông báo"
    elif title == "Info":
        title = "Thông báo"
    original_showinfo(title, message, **kwargs)

messagebox.showinfo = custom_showinfo

def check_empty_treeview(tree, message="Chưa có dữ liệu"):
    if not tree.get_children():
        values = [message] + [""] * (len(tree["columns"]) - 1)
        tree.insert("", "end", values=values, tags=("oddrow",))

# Hạn hủy đăng ký (ngày)
UNENROLL_DEADLINE_DAYS = 7

# Đơn giá học phí mỗi tín chỉ (VNĐ) — mặc định khi tạo lớp HP
TUITION_PER_CREDIT = 500_000

# ── UI THEME CONSTANTS ──────────────────────────────────────────────────────
COLOR_BG       = "#F5F7FA"
COLOR_PRIMARY  = "#0F6E71"
COLOR_DANGER   = "#E5484D"
COLOR_WARNING  = "#F5A623"
COLOR_SUCCESS  = "#28A745"
COLOR_TEXT     = "#1A1A2E"
COLOR_TOPBAR   = "#0B5B5D"
COLOR_ROW_EVEN = "#EDF2F7"
COLOR_ROW_ODD  = "#FFFFFF"

FONT_TITLE  = ("Segoe UI", 18, "bold")
FONT_BODY   = ("Segoe UI", 11)
FONT_BODY_BOLD = ("Segoe UI", 11, "bold")
FONT_LABEL  = ("Segoe UI", 11)
FONT_ENTRY  = ("Segoe UI", 11)
FONT_BTN    = ("Segoe UI", 11, "bold")
FONT_BTN_LG = ("Segoe UI", 13, "bold")
FONT_TOPBAR = ("Segoe UI", 12, "bold")

FONT_CARD_TITLE = ("Segoe UI", 11)
FONT_CARD_VALUE = ("Segoe UI", 28, "bold")
COLOR_CARD_BG   = "#FFFFFF"
COLOR_CARD_BD   = "#D0D7DE"
# ─────────────────────────────────────────────────────────────────────────────

db = None  # Initialized once by LoginWindow


def _sem_display(sem):
    """Build a display string for a semester record or business query row.

    Format: 'HK1 (2025-2026)'
    Never returns a transaction ID, enrollment ID, or class section ID as semester name.
    """
    if not sem or not isinstance(sem, dict):
        return ""

    name = sem.get('semester_name') or sem.get('name')
    if not name and 'semester_id' in sem and not any(k in sem for k in ('amount', 'midterm', 'final_score')):
        name = sem.get('semester_id')

    year = sem.get('year_name') or sem.get('academic_year_name') or sem.get('academic_year')

    if name and year:
        return f"{name} ({year})"
    elif name:
        return str(name)
    elif year:
        return str(year)
    else:
        return "N/A"


def _sem_cb_value(sem):
    """Build the combobox value string for a semester."""
    return f"{sem['id']} - {_sem_display(sem)}"


# ── TTK STYLE SETUP ─────────────────────────────────────────────────────────
def setup_styles():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Treeview", background=COLOR_ROW_ODD, foreground=COLOR_TEXT,
                     rowheight=28, fieldbackground=COLOR_ROW_ODD, font=FONT_BODY)
    style.configure("Treeview.Heading", background=COLOR_PRIMARY, foreground="white",
                     font=("Segoe UI", 11, "bold"), relief="flat")
    style.map("Treeview.Heading", background=[("active", COLOR_TOPBAR)])
    style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
    style.configure("TNotebook.Tab", background="#DDE3EA", foreground=COLOR_TEXT,
                     font=FONT_BODY, padding=[14, 6])
    style.map("TNotebook.Tab", background=[("selected", COLOR_PRIMARY)],
              foreground=[("selected", "white")])
    style.configure("TCombobox", font=FONT_BODY)
    style.map("TCombobox", fieldbackground=[("readonly", "white")],
              selectbackground=[("readonly", "white")],
              selectforeground=[("readonly", COLOR_TEXT)])


def _configure_treeview_tags(tree):
    tree.tag_configure("evenrow", background=COLOR_ROW_EVEN)
    tree.tag_configure("oddrow", background=COLOR_ROW_ODD)


def _make_card(parent, title, value, col, accent=COLOR_PRIMARY):
    card = tk.Frame(parent, bg=COLOR_CARD_BG, highlightbackground=COLOR_CARD_BD,
                    highlightthickness=1, padx=24, pady=18)
    card.grid(row=0, column=col, padx=14, pady=14, sticky="nsew")
    tk.Label(card, text=title, font=FONT_CARD_TITLE, bg=COLOR_CARD_BG,
             fg="#6B7280").pack(anchor="w")
    tk.Label(card, text=str(value), font=FONT_CARD_VALUE, bg=COLOR_CARD_BG,
             fg=accent).pack(anchor="w", pady=(8, 0))
    return card


def _make_btn(parent, text, command, bg=COLOR_PRIMARY, width=15, font=FONT_BTN):
    return tk.Button(parent, text=text, bg=bg, fg="white", font=font,
                     width=width, relief="flat", cursor="hand2",
                     activebackground=COLOR_TOPBAR, activeforeground="white",
                     command=command)


def _get_schedule_display(db_inst, section_id):
    """Build human-readable schedule string from section_schedules table."""
    rows = db_inst.get_section_schedules(section_id)
    if not rows:
        return "—"
    sessions = [(r['weekday'], r['start_minutes'], r['end_minutes']) for r in rows]
    return format_schedule_list(sessions)


# ═══════════════════════════════════════════════════════════════════════════
# LOGIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════

def _close_session_window(root):
    from .session import session
    session.logout()
    root.destroy()


class LoginWindow:
    def __init__(self):
        global db
        from .session import session
        session.logout()
        self.root = tk.Tk()
        self.root.protocol("WM_DELETE_WINDOW", lambda: _close_session_window(self.root))
        if db is None:
            self.root.withdraw()
            try:
                db = Database()
            except Exception as exc:
                # Show the real config/port error so the user can act on it
                msg = str(exc)
                messagebox.showerror("Lỗi kết nối", msg, parent=self.root)
                self.root.destroy()
                return
            self.root.deiconify()

        # ── Check migration readiness ──
        if not db.is_ready:
            messagebox.showerror(
                "Migration chưa hoàn tất",
                "Cơ sở dữ liệu chưa được nâng cấp xong.\n"
                "Vui lòng chạy migration trước khi sử dụng ứng dụng.\n\n"
                "cd \"Student Management System\"\n"
                "python -m gui.migration --apply",
                parent=self.root)
            self.root.destroy()
            return

        self.root.title("Hệ thống Quản lý Sinh viên")
        self.root.geometry("950x550")
        self.root.configure(bg="white")
        self.root.resizable(True, True)

        setup_styles()

        left_panel = tk.Frame(self.root, bg=COLOR_PRIMARY, width=400)
        left_panel.pack(side="left", fill="y")
        left_panel.pack_propagate(False)

        left_spacer = tk.Frame(left_panel, bg=COLOR_PRIMARY)
        left_spacer.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(left_spacer, text="🎓", font=("Segoe UI", 52),
                 bg=COLOR_PRIMARY, fg="white").pack(pady=(0, 10))
        tk.Label(left_spacer, text="HỆ THỐNG\nQUẢN LÝ SINH VIÊN",
                 font=("Segoe UI", 22, "bold"), bg=COLOR_PRIMARY, fg="white",
                 justify="center", wraplength=320).pack(pady=(0, 12))

        right_panel = tk.Frame(self.root, bg="white")
        right_panel.pack(side="right", fill="both", expand=True)

        form_container = tk.Frame(right_panel, bg="white")
        form_container.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(form_container, text="ĐĂNG NHẬP",
                 font=("Segoe UI", 20, "bold"), bg="white",
                 fg=COLOR_PRIMARY).pack(pady=(0, 6))
        tk.Label(form_container, text="Vui lòng đăng nhập để tiếp tục",
                 font=("Segoe UI", 10), bg="white", fg="#888888").pack(pady=(0, 20))

        self.mode = tk.StringVar(value="login")
        self.form_frame = tk.LabelFrame(form_container, text="Đăng nhập", bg="white",
                                         fg=COLOR_PRIMARY, font=FONT_BODY,
                                         padx=20, pady=15)
        self.form_frame.pack(pady=(0, 20), padx=30)

        btn_frame = tk.Frame(form_container, bg="white")
        btn_frame.pack(pady=(0, 10))
        self.main_btn = tk.Button(btn_frame, text="ĐĂNG NHẬP", width=30, height=2,
                                bg=COLOR_PRIMARY, fg="white", font=FONT_BTN_LG,
                                activebackground=COLOR_TOPBAR, activeforeground="white",
                                relief="flat", cursor="hand2",
                                command=self.handle_action)
        self.main_btn.pack()

        self.show_login_form()
        self.mode.trace("w", lambda *_: self.toggle_mode())
        self.root.mainloop()

    def show_login_form(self):
        for w in self.form_frame.winfo_children(): w.destroy()
        tk.Label(self.form_frame, text="Vai trò:", bg="white", font=FONT_LABEL).grid(row=0, column=0, sticky="w", pady=12)
        self.role_var = tk.StringVar(value="Sinh viên")
        ttk.Combobox(self.form_frame, textvariable=self.role_var,
                    values=["Sinh viên", "Giảng viên", "Quản trị viên"], state="readonly", width=30).grid(row=0, column=1, pady=12, padx=12)
        tk.Label(self.form_frame, text="Tên đăng nhập:", bg="white", font=FONT_LABEL).grid(row=1, column=0, sticky="w", pady=12)
        self.user_entry = tk.Entry(self.form_frame, width=32, font=FONT_ENTRY); self.user_entry.grid(row=1, column=1, pady=12, padx=12)
        tk.Label(self.form_frame, text="Mật khẩu:", bg="white", font=FONT_LABEL).grid(row=2, column=0, sticky="w", pady=12)
        self.pass_entry = tk.Entry(self.form_frame, width=32, font=FONT_ENTRY, show="*"); self.pass_entry.grid(row=2, column=1, pady=12, padx=12)
        self.main_btn.config(text="ĐĂNG NHẬP")

    def show_register_form(self):
        for w in self.form_frame.winfo_children(): w.destroy()
        entries = ["Họ và tên:", "Email:", "Tên đăng nhập:", "Mật khẩu:", "Xác nhận mật khẩu:", "Số điện thoại:", "Địa chỉ:"]
        self.reg_entries = []
        for i, text in enumerate(entries):
            tk.Label(self.form_frame, text=text, bg="white", font=FONT_LABEL).grid(row=i, column=0, sticky="w", pady=6)
            e = tk.Entry(self.form_frame, width=32, font=FONT_ENTRY, show="*" if "Mật khẩu" in text else "")
            e.grid(row=i, column=1, pady=6, padx=12)
            self.reg_entries.append(e)
        self.main_btn.config(text="Đăng ký")

    def toggle_mode(self):
        if self.mode.get() == "login": self.show_login_form()

    def handle_action(self):
        if self.mode.get() == "login": self.login()

    def login(self):
        role_disp = self.role_var.get()
        role_map = {"Sinh viên": "Student", "Giảng viên": "Lecturer", "Quản trị viên": "Admin"}
        role = role_map.get(role_disp, role_disp)
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()
        if not username or not password:
            messagebox.showerror("Lỗi", "Vui lòng nhập đầy đủ thông tin"); return
        try:
            from .session import session
            ok = session.login(db, username, password, role)
        except Exception as e:
            messagebox.showerror("Lỗi cơ sở dữ liệu", f"Không thể kết nối cơ sở dữ liệu. Vui lòng kiểm tra lại cấu hình kết nối."); return
        if ok:
            self.root.destroy()
            if role == "Admin":
                AdminDashboard(username)
            elif role == "Lecturer":
                LecturerDashboard(username)
            else:
                StudentDashboard(username)
        else:
            messagebox.showerror("Đăng nhập thất bại", "Tên đăng nhập hoặc mật khẩu không chính xác")


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

class AdminDashboard:
    def __init__(self, username):
        self.username = username
        self.root = tk.Tk()
        self.root.protocol("WM_DELETE_WINDOW", lambda: _close_session_window(self.root))
        self.root.title(f"Quản trị viên - {username}")
        self.root.geometry("1200x750")
        self.root.minsize(1024, 600)
        self.root.resizable(True, True)
        self.root.configure(bg=COLOR_BG)

        sidebar = tk.Frame(self.root, bg=COLOR_TOPBAR, width=230)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="👤 Admin", font=("Segoe UI", 10),
                 bg=COLOR_TOPBAR, fg="#B2DFDB").pack(pady=(18, 2))
        tk.Label(sidebar, text=username, font=("Segoe UI", 13, "bold"),
                 bg=COLOR_TOPBAR, fg="white").pack(pady=(0, 18))
        tk.Frame(sidebar, bg="#1A8A8D", height=1).pack(fill="x", padx=15, pady=(0, 10))

        menu_items = [
            "📊  Tổng quan",
            "🏛️  Khoa / Ngành",
            "📅  Năm học & Học kỳ",
            "🏫  Khóa TS & Lớp HC",
            "📖  Danh mục Môn học",
            "📚  Lớp học phần",
            "👨‍🏫  Tạo tài khoản GV",
            "🎓  Quản lý Sinh viên",
        ]

        self.sidebar_buttons = []
        for i, text in enumerate(menu_items):
            btn = tk.Button(sidebar, text=text, font=("Segoe UI", 11),
                            bg=COLOR_TOPBAR, fg="white", relief="flat",
                            anchor="w", padx=18, pady=10, cursor="hand2",
                            activebackground=COLOR_PRIMARY, activeforeground="white",
                            command=lambda idx=i: self._show_page(idx))
            btn.pack(fill="x")
            self.sidebar_buttons.append(btn)

        tk.Frame(sidebar, bg=COLOR_TOPBAR).pack(fill="both", expand=True)
        tk.Button(sidebar, text="🚪  Đăng xuất", font=FONT_BTN,
                  bg=COLOR_DANGER, fg="white", relief="flat", cursor="hand2", pady=10,
                  activebackground="#C13639", activeforeground="white",
                  command=self.logout).pack(fill="x", padx=12, pady=15)

        content = tk.Frame(self.root, bg=COLOR_BG)
        content.pack(side="right", fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.pages = []
        page_builders = [
            self.build_overview,
            self.build_dept_program,
            self.build_academic,
            self.build_batch_class,
            self.build_subjects,
            self.build_sections,
            self.build_create_lecturer,
            self.build_students,
        ]
        for builder in page_builders:
            page = tk.Frame(content, bg=COLOR_BG)
            page.grid(row=0, column=0, sticky="nsew")
            builder(page)
            self.pages.append(page)

        self._show_page(0)
        self.root.mainloop()

    def _show_page(self, index):
        self.pages[index].tkraise()
        for i, btn in enumerate(self.sidebar_buttons):
            if i == index:
                btn.config(bg=COLOR_PRIMARY, font=("Segoe UI", 11, "bold"))
            else:
                btn.config(bg=COLOR_TOPBAR, font=("Segoe UI", 11))

    def logout(self):
        if messagebox.askyesno("Đăng xuất", "Bạn có chắc muốn đăng xuất?"):
            from .session import session
            session.logout()
            self.root.destroy()
            LoginWindow()

    def build_overview(self, parent):
        self.overview_parent = parent
        tk.Label(parent, text="TỔNG QUAN HỆ THỐNG", font=FONT_TITLE, bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(30, 20))
        self.cards_frame = tk.Frame(parent, bg=COLOR_BG)
        self.cards_frame.pack(padx=30, pady=10)
        
        self.nb_stats = ttk.Notebook(parent)
        self.nb_stats.pack(fill="both", expand=True, padx=30, pady=20)
        
        self.tab_status = tk.Frame(self.nb_stats, bg=COLOR_BG)
        self.nb_stats.add(self.tab_status, text="Theo trạng thái")
        self.tab_dept = tk.Frame(self.nb_stats, bg=COLOR_BG)
        self.nb_stats.add(self.tab_dept, text="Theo khoa")
        self.tab_prog = tk.Frame(self.nb_stats, bg=COLOR_BG)
        self.nb_stats.add(self.tab_prog, text="Theo ngành")
        self.tab_batch = tk.Frame(self.nb_stats, bg=COLOR_BG)
        self.nb_stats.add(self.tab_batch, text="Theo khóa TS")
        self.tab_class = tk.Frame(self.nb_stats, bg=COLOR_BG)
        self.nb_stats.add(self.tab_class, text="Theo lớp HC")
        
        def create_tree(tab, columns):
            tree = ttk.Treeview(tab, columns=columns, show="headings")
            for c in columns:
                tree.heading(c, text=c)
                tree.column(c, width=200)
            scrollbar = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            tree.pack(fill="both", expand=True)
            _configure_treeview_tags(tree)
            return tree
            
        self.tree_status = create_tree(self.tab_status, ("Trạng thái", "Số lượng"))
        self.tree_dept = create_tree(self.tab_dept, ("Tên Khoa", "Số lượng"))
        self.tree_prog = create_tree(self.tab_prog, ("Tên Ngành", "Số lượng"))
        self.tree_batch = create_tree(self.tab_batch, ("Tên Khóa", "Số lượng"))
        self.tree_class = create_tree(self.tab_class, ("Tên Lớp", "Số lượng"))
        
        self.refresh_overview()
        
    def refresh_overview(self):
        for w in self.cards_frame.winfo_children(): w.destroy()
        for c in range(4): self.cards_frame.grid_columnconfigure(c, weight=1)
        
        total_subjects = len(db.list_subjects())
        total_lecturers = db.count_lecturers()
        total_enrollments = db.count_all_enrollments()
        stats = db.get_student_statistics()
        
        _make_card(self.cards_frame, "Tổng số môn học", total_subjects, 0)
        _make_card(self.cards_frame, "Tổng số sinh viên", stats['total_students'], 1)
        _make_card(self.cards_frame, "Tổng số giảng viên", total_lecturers, 2)
        _make_card(self.cards_frame, "Tổng lượt đăng ký", total_enrollments, 3)
        
        def populate_tree(tree, data):
            for t in tree.get_children(): tree.delete(t)
            for i, row in enumerate(data):
                tag = "evenrow" if i % 2 == 0 else "oddrow"
                keys = list(row.keys())
                tree.insert("", "end", values=(row[keys[0]], row['cnt']), tags=(tag,))
                
        populate_tree(self.tree_status, stats['by_status'])
        populate_tree(self.tree_dept, stats['by_department'])
        populate_tree(self.tree_prog, stats['by_program'])
        populate_tree(self.tree_batch, stats['by_batch'])
        populate_tree(self.tree_class, stats['by_admin_class'])

    # ── DEPARTMENT / PROGRAM ─────────────────────────────────────────────
    def build_dept_program(self, parent):
        tk.Label(parent, text="QUẢN LÝ KHOA / NGÀNH", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(20, 10))

        # Department section
        dept_frame = tk.LabelFrame(parent, text="Thêm Khoa", bg=COLOR_BG,
                                    fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=10)
        dept_frame.pack(fill="x", padx=30, pady=5)
        tk.Label(dept_frame, text="Mã khoa:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.dept_id_entry = tk.Entry(dept_frame, width=15, font=FONT_ENTRY)
        self.dept_id_entry.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(dept_frame, text="Tên khoa:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.dept_name_entry = tk.Entry(dept_frame, width=30, font=FONT_ENTRY)
        self.dept_name_entry.grid(row=0, column=3, padx=5, pady=5)
        _make_btn(dept_frame, "Thêm Khoa", self.add_department, width=12).grid(row=0, column=4, padx=5, pady=5)
        _make_btn(dept_frame, "Sửa Khoa", self.edit_department, bg=COLOR_WARNING, width=10).grid(row=0, column=5, padx=5, pady=5)

        # Program section
        prog_frame = tk.LabelFrame(parent, text="Thêm Ngành", bg=COLOR_BG,
                                    fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=10)
        prog_frame.pack(fill="x", padx=30, pady=5)
        tk.Label(prog_frame, text="Mã ngành:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.prog_id_entry = tk.Entry(prog_frame, width=15, font=FONT_ENTRY)
        self.prog_id_entry.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(prog_frame, text="Tên ngành:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.prog_name_entry = tk.Entry(prog_frame, width=25, font=FONT_ENTRY)
        self.prog_name_entry.grid(row=0, column=3, padx=5, pady=5)
        tk.Label(prog_frame, text="Khoa:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=4, padx=5, pady=5, sticky="w")
        self.prog_dept_var = tk.StringVar()
        self.prog_dept_cb = ttk.Combobox(prog_frame, textvariable=self.prog_dept_var, state="readonly", width=15)
        self.prog_dept_cb.grid(row=0, column=5, padx=5, pady=5)
        _make_btn(prog_frame, "Thêm Ngành", self.add_program, width=12).grid(row=0, column=6, padx=5, pady=5)
        _make_btn(prog_frame, "Sửa Ngành", self.edit_program, bg=COLOR_WARNING, width=10).grid(row=0, column=7, padx=5, pady=5)

        # Tables
        cols_d = ("Mã khoa", "Tên khoa")
        dept_frame = tk.Frame(parent)
        dept_frame.pack(fill="x", padx=30, pady=5)
        self.dept_tree = ttk.Treeview(dept_frame, columns=cols_d, show="headings", height=5)
        dept_scroll = ttk.Scrollbar(dept_frame, orient="vertical", command=self.dept_tree.yview)
        self.dept_tree.configure(yscrollcommand=dept_scroll.set)
        self.dept_tree.pack(side="left", fill="x", expand=True)
        dept_scroll.pack(side="right", fill="y")
        for c in cols_d: self.dept_tree.heading(c, text=c); self.dept_tree.column(c, width=200)
        _configure_treeview_tags(self.dept_tree)

        cols_p = ("Mã ngành", "Tên ngành", "Khoa")
        prog_frame = tk.Frame(parent)
        prog_frame.pack(fill="both", expand=True, padx=30, pady=5)
        self.prog_tree = ttk.Treeview(prog_frame, columns=cols_p, show="headings", height=5)
        prog_scroll = ttk.Scrollbar(prog_frame, orient="vertical", command=self.prog_tree.yview)
        self.prog_tree.configure(yscrollcommand=prog_scroll.set)
        self.prog_tree.pack(side="left", fill="both", expand=True)
        prog_scroll.pack(side="right", fill="y")
        for c in cols_p: self.prog_tree.heading(c, text=c); self.prog_tree.column(c, width=200)
        _configure_treeview_tags(self.prog_tree)

        self.refresh_dept_prog()

    def refresh_dept_prog(self):
        for t in self.dept_tree.get_children(): self.dept_tree.delete(t)
        depts = db.list_departments()
        for i, d in enumerate(depts):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.dept_tree.insert("", "end", values=(d['id'], d['name']), tags=(tag,))
        self.prog_dept_cb['values'] = [f"{d['id']} - {d['name']}" for d in depts]

        for t in self.prog_tree.get_children(): self.prog_tree.delete(t)
        progs = db.list_programs()
        for i, p in enumerate(progs):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.prog_tree.insert("", "end", values=(p['id'], p['name'], p.get('dept_name', '')), tags=(tag,))

    def add_department(self):
        did = self.dept_id_entry.get().strip().upper()
        name = self.dept_name_entry.get().strip()
        if not did or not name:
            messagebox.showerror("Error", "Điền đầy đủ mã và tên khoa"); return
        try:
            db.add_department(did, name)
            messagebox.showinfo("Success", f"Đã thêm khoa {did}")
            self.dept_id_entry.delete(0, "end")
            self.dept_name_entry.delete(0, "end")
            self.refresh_dept_prog()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def edit_department(self):
        item = self.dept_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một khoa để sửa"); return
        did = str(self.dept_tree.item(item[0])['values'][0])
        old_name = str(self.dept_tree.item(item[0])['values'][1])
        new_name = simpledialog.askstring("Sửa Khoa", f"Tên mới cho khoa {did}:", initialvalue=old_name)
        if not new_name or not new_name.strip():
            return
        try:
            db.update_department(did, name=new_name.strip())
            messagebox.showinfo("Success", "Đã cập nhật")
            self.refresh_dept_prog()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def add_program(self):
        pid = self.prog_id_entry.get().strip().upper()
        name = self.prog_name_entry.get().strip()
        dept_sel = self.prog_dept_var.get()
        if not pid or not name or not dept_sel:
            messagebox.showerror("Error", "Điền đầy đủ thông tin ngành"); return
        dept_id = dept_sel.split(" - ")[0]
        try:
            db.add_program(pid, name, dept_id)
            messagebox.showinfo("Success", f"Đã thêm ngành {pid}")
            self.prog_id_entry.delete(0, "end")
            self.prog_name_entry.delete(0, "end")
            self.refresh_dept_prog()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def refresh_all_admin_comboboxes(self):
        """Refresh all catalog trees and dependent comboboxes across Admin Dashboard."""
        self.refresh_dept_prog()
        self.refresh_academic()
        self.refresh_batch_class()
        self.refresh_subjects()
        self.refresh_courses()
        self.refresh_students()

    def edit_program(self):
        item = self.prog_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một ngành để sửa"); return
        pid = str(self.prog_tree.item(item[0])['values'][0])
        prog = db.get_program(pid)
        if not prog:
            messagebox.showerror("Error", f"Ngành {pid} không tồn tại"); return

        top = tk.Toplevel(self.root)
        top.title(f"Sửa Ngành - {pid}")
        top.geometry("400x250")
        top.grab_set()

        tk.Label(top, text=f"Mã ngành: {pid}", font=FONT_BODY_BOLD).pack(pady=(15, 10))

        f_name = tk.Frame(top)
        f_name.pack(fill="x", padx=20, pady=5)
        tk.Label(f_name, text="Tên ngành:", width=12, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_name = tk.Entry(f_name, width=28, font=FONT_ENTRY)
        entry_name.insert(0, prog['name'])
        entry_name.pack(side="left")

        f_dept = tk.Frame(top)
        f_dept.pack(fill="x", padx=20, pady=5)
        tk.Label(f_dept, text="Khoa:", width=12, anchor="w", font=FONT_LABEL).pack(side="left")
        depts = db.list_departments()
        dept_vals = [f"{d['id']} - {d['name']}" for d in depts]
        var_dept = tk.StringVar()
        cb_dept = ttk.Combobox(f_dept, textvariable=var_dept, values=dept_vals, state="readonly", width=26)
        curr_dept_val = next((v for v in dept_vals if v.startswith(str(prog['department_id']) + " -")), dept_vals[0] if dept_vals else "")
        var_dept.set(curr_dept_val)
        cb_dept.pack(side="left")

        def save():
            name = entry_name.get().strip()
            dept_sel = var_dept.get()
            if not name or not dept_sel:
                messagebox.showerror("Error", "Vui lòng nhập đầy đủ thông tin", parent=top)
                return
            dept_id = dept_sel.split(" - ")[0]
            try:
                db.update_program(pid, name=name, department_id=dept_id)
                messagebox.showinfo("Success", "Đã cập nhật ngành", parent=top)
                top.destroy()
                self.refresh_all_admin_comboboxes()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=top)

        _make_btn(top, "Lưu thay đổi", save, bg=COLOR_PRIMARY, width=15).pack(pady=20)

    # ── ACADEMIC YEAR & SEMESTER ─────────────────────────────────────────
    def build_academic(self, parent):
        tk.Label(parent, text="NĂM HỌC & HỌC KỲ", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(20, 10))

        ay_frame = tk.LabelFrame(parent, text="Thêm Năm học", bg=COLOR_BG,
                                  fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=10)
        ay_frame.pack(fill="x", padx=30, pady=5)
        tk.Label(ay_frame, text="Mã:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5)
        self.ay_id = tk.Entry(ay_frame, width=12, font=FONT_ENTRY); self.ay_id.grid(row=0, column=1, padx=5)
        tk.Label(ay_frame, text="Tên:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5)
        self.ay_name = tk.Entry(ay_frame, width=20, font=FONT_ENTRY); self.ay_name.grid(row=0, column=3, padx=5)
        tk.Label(ay_frame, text="Năm BĐ:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=4, padx=5)
        self.ay_start = tk.Entry(ay_frame, width=6, font=FONT_ENTRY); self.ay_start.grid(row=0, column=5, padx=5)
        tk.Label(ay_frame, text="Năm KT:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=6, padx=5)
        self.ay_end = tk.Entry(ay_frame, width=6, font=FONT_ENTRY); self.ay_end.grid(row=0, column=7, padx=5)
        _make_btn(ay_frame, "Thêm", self.add_academic_year, width=8).grid(row=0, column=8, padx=5)
        _make_btn(ay_frame, "Sửa", self.edit_academic_year, bg=COLOR_WARNING, width=6).grid(row=0, column=9, padx=5)

        sem_frame = tk.LabelFrame(parent, text="Thêm Học kỳ", bg=COLOR_BG,
                                   fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=10)
        sem_frame.pack(fill="x", padx=30, pady=5)
        tk.Label(sem_frame, text="Mã HK:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5)
        self.sem_id = tk.Entry(sem_frame, width=12, font=FONT_ENTRY); self.sem_id.grid(row=0, column=1, padx=5)
        tk.Label(sem_frame, text="Tên HK:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5)
        self.sem_name = tk.Entry(sem_frame, width=15, font=FONT_ENTRY); self.sem_name.grid(row=0, column=3, padx=5)
        tk.Label(sem_frame, text="Năm học:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=4, padx=5)
        self.sem_ay_var = tk.StringVar()
        self.sem_ay_cb = ttk.Combobox(sem_frame, textvariable=self.sem_ay_var, state="readonly", width=18)
        self.sem_ay_cb.grid(row=0, column=5, padx=5)
        self.sem_reg_var = tk.IntVar(value=0)
        tk.Checkbutton(sem_frame, text="Mở ĐK", variable=self.sem_reg_var, bg=COLOR_BG).grid(row=0, column=6, padx=5)
        _make_btn(sem_frame, "Thêm", self.add_semester, width=8).grid(row=0, column=7, padx=5)
        _make_btn(sem_frame, "Sửa học kỳ", self.edit_semester, bg=COLOR_WARNING, width=10).grid(row=0, column=8, padx=5)

        # Date editing row
        date_frame = tk.LabelFrame(parent, text="Sửa nhanh ngày học kỳ", bg=COLOR_BG,
                                    fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=10)
        date_frame.pack(fill="x", padx=30, pady=5)
        tk.Label(date_frame, text="Ngày BĐ (YYYY-MM-DD):", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5)
        self.sem_start_date = tk.Entry(date_frame, width=12, font=FONT_ENTRY)
        self.sem_start_date.grid(row=0, column=1, padx=5)
        tk.Label(date_frame, text="Ngày KT:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5)
        self.sem_end_date = tk.Entry(date_frame, width=12, font=FONT_ENTRY)
        self.sem_end_date.grid(row=0, column=3, padx=5)
        _make_btn(date_frame, "Cập nhật ngày", self.update_semester_dates, bg=COLOR_WARNING, width=14).grid(row=0, column=4, padx=10)

        btn_f = tk.Frame(parent, bg=COLOR_BG)
        btn_f.pack(pady=5)
        _make_btn(btn_f, "Mở/Đóng ĐK học kỳ", self.toggle_semester_reg, bg=COLOR_WARNING, width=20).pack()

        cols_ay = ("Mã", "Tên", "Năm BĐ", "Năm KT")
        ay_frame = tk.Frame(parent)
        ay_frame.pack(fill="x", padx=30, pady=5)
        self.ay_tree = ttk.Treeview(ay_frame, columns=cols_ay, show="headings", height=4)
        ay_scroll = ttk.Scrollbar(ay_frame, orient="vertical", command=self.ay_tree.yview)
        self.ay_tree.configure(yscrollcommand=ay_scroll.set)
        self.ay_tree.pack(side="left", fill="x", expand=True)
        ay_scroll.pack(side="right", fill="y")
        for c in cols_ay: self.ay_tree.heading(c, text=c); self.ay_tree.column(c, width=150)
        _configure_treeview_tags(self.ay_tree)

        cols_sem = ("Mã HK", "Tên HK", "Năm học", "Ngày BĐ", "Ngày KT", "Đăng ký")
        sem_frame = tk.Frame(parent)
        sem_frame.pack(fill="both", expand=True, padx=30, pady=5)
        self.sem_tree = ttk.Treeview(sem_frame, columns=cols_sem, show="headings", height=5)
        sem_scroll = ttk.Scrollbar(sem_frame, orient="vertical", command=self.sem_tree.yview)
        self.sem_tree.configure(yscrollcommand=sem_scroll.set)
        self.sem_tree.pack(side="left", fill="both", expand=True)
        sem_scroll.pack(side="right", fill="y")
        for c in cols_sem: self.sem_tree.heading(c, text=c); self.sem_tree.column(c, width=130)
        _configure_treeview_tags(self.sem_tree)

        self.refresh_academic()

    def refresh_academic(self):
        for t in self.ay_tree.get_children(): self.ay_tree.delete(t)
        years = db.list_academic_years()
        for i, y in enumerate(years):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.ay_tree.insert("", "end", values=(y['id'], y['name'], y.get('start_year', ''), y.get('end_year', '')), tags=(tag,))
        self.sem_ay_cb['values'] = [f"{y['id']} - {y['name']}" for y in years]

        for t in self.sem_tree.get_children(): self.sem_tree.delete(t)
        sems = db.list_semesters()
        for i, s in enumerate(sems):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            reg = "✅ Mở" if s['registration_open'] else "❌ Đóng"
            sd = str(s.get('start_date', '')) if s.get('start_date') else '—'
            ed = str(s.get('end_date', '')) if s.get('end_date') else '—'
            self.sem_tree.insert("", "end", values=(
                s['id'], s['name'], s.get('year_name', ''), sd, ed, reg
            ), tags=(tag,))

    def add_academic_year(self):
        yid = self.ay_id.get().strip()
        name = self.ay_name.get().strip()
        if not yid or not name:
            messagebox.showerror("Error", "Điền mã và tên năm học"); return
        try:
            sy = int(self.ay_start.get()) if self.ay_start.get().strip() else None
            ey = int(self.ay_end.get()) if self.ay_end.get().strip() else None
        except ValueError:
            messagebox.showerror("Error", "Năm phải là số"); return
        try:
            db.add_academic_year(yid, name, sy, ey)
            messagebox.showinfo("Success", f"Đã thêm năm học {yid}")
            self.ay_id.delete(0, "end"); self.ay_name.delete(0, "end")
            self.ay_start.delete(0, "end"); self.ay_end.delete(0, "end")
            self.refresh_academic()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def edit_academic_year(self):
        item = self.ay_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một năm học để sửa"); return
        yid = str(self.ay_tree.item(item[0])['values'][0])
        ay = db.get_academic_year(yid)
        if not ay:
            messagebox.showerror("Error", f"Năm học {yid} không tồn tại"); return

        top = tk.Toplevel(self.root)
        top.title(f"Sửa Năm học - {yid}")
        top.geometry("400x280")
        top.grab_set()

        tk.Label(top, text=f"Mã năm học: {yid}", font=FONT_BODY_BOLD).pack(pady=(15, 10))

        f_name = tk.Frame(top)
        f_name.pack(fill="x", padx=20, pady=5)
        tk.Label(f_name, text="Tên năm học:", width=14, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_name = tk.Entry(f_name, width=25, font=FONT_ENTRY)
        entry_name.insert(0, ay['name'])
        entry_name.pack(side="left")

        f_sy = tk.Frame(top)
        f_sy.pack(fill="x", padx=20, pady=5)
        tk.Label(f_sy, text="Năm bắt đầu:", width=14, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_sy = tk.Entry(f_sy, width=25, font=FONT_ENTRY)
        if ay.get('start_year') is not None:
            entry_sy.insert(0, str(ay['start_year']))
        entry_sy.pack(side="left")

        f_ey = tk.Frame(top)
        f_ey.pack(fill="x", padx=20, pady=5)
        tk.Label(f_ey, text="Năm kết thúc:", width=14, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_ey = tk.Entry(f_ey, width=25, font=FONT_ENTRY)
        if ay.get('end_year') is not None:
            entry_ey.insert(0, str(ay['end_year']))
        entry_ey.pack(side="left")

        def save():
            name = entry_name.get().strip()
            sy_s = entry_sy.get().strip()
            ey_s = entry_ey.get().strip()
            if not name:
                messagebox.showerror("Error", "Tên năm học không được để trống", parent=top)
                return
            try:
                sy = int(sy_s) if sy_s else None
                ey = int(ey_s) if ey_s else None
            except ValueError:
                messagebox.showerror("Error", "Năm phải là số nguyên", parent=top)
                return
            try:
                db.update_academic_year(yid, name=name, start_year=sy, end_year=ey)
                messagebox.showinfo("Success", "Đã cập nhật năm học", parent=top)
                top.destroy()
                self.refresh_all_admin_comboboxes()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=top)

        _make_btn(top, "Lưu thay đổi", save, bg=COLOR_PRIMARY, width=15).pack(pady=15)

    def add_semester(self):
        sid = self.sem_id.get().strip()
        name = self.sem_name.get().strip()
        ay_sel = self.sem_ay_var.get()
        if not sid or not name or not ay_sel:
            messagebox.showerror("Error", "Điền đầy đủ thông tin học kỳ"); return
        ay_id = ay_sel.split(" - ")[0]
        try:
            db.add_semester(sid, name, ay_id, registration_open=self.sem_reg_var.get())
            messagebox.showinfo("Success", f"Đã thêm học kỳ {sid}")
            self.sem_id.delete(0, "end"); self.sem_name.delete(0, "end")
            self.refresh_academic()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def edit_semester(self):
        item = self.sem_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một học kỳ để sửa"); return
        sid = str(self.sem_tree.item(item[0])['values'][0])
        sem = db.get_semester(sid)
        if not sem:
            messagebox.showerror("Error", f"Học kỳ {sid} không tồn tại"); return

        top = tk.Toplevel(self.root)
        top.title(f"Sửa Học kỳ - {sid}")
        top.geometry("450x360")
        top.grab_set()

        tk.Label(top, text=f"Mã học kỳ: {sid}", font=FONT_BODY_BOLD).pack(pady=(15, 10))

        f_name = tk.Frame(top)
        f_name.pack(fill="x", padx=20, pady=5)
        tk.Label(f_name, text="Tên học kỳ:", width=14, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_name = tk.Entry(f_name, width=28, font=FONT_ENTRY)
        entry_name.insert(0, sem['name'])
        entry_name.pack(side="left")

        f_ay = tk.Frame(top)
        f_ay.pack(fill="x", padx=20, pady=5)
        tk.Label(f_ay, text="Năm học:", width=14, anchor="w", font=FONT_LABEL).pack(side="left")
        years = db.list_academic_years()
        ay_vals = [f"{y['id']} - {y['name']}" for y in years]
        var_ay = tk.StringVar()
        cb_ay = ttk.Combobox(f_ay, textvariable=var_ay, values=ay_vals, state="readonly", width=26)
        curr_ay = next((v for v in ay_vals if v.startswith(sem['academic_year_id'] + " -")), ay_vals[0] if ay_vals else "")
        var_ay.set(curr_ay)
        cb_ay.pack(side="left")

        f_sd = tk.Frame(top)
        f_sd.pack(fill="x", padx=20, pady=5)
        tk.Label(f_sd, text="Ngày BĐ (YYYY-MM-DD):", width=20, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_sd = tk.Entry(f_sd, width=20, font=FONT_ENTRY)
        if sem.get('start_date'):
            entry_sd.insert(0, str(sem['start_date']))
        entry_sd.pack(side="left")

        f_ed = tk.Frame(top)
        f_ed.pack(fill="x", padx=20, pady=5)
        tk.Label(f_ed, text="Ngày KT (YYYY-MM-DD):", width=20, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_ed = tk.Entry(f_ed, width=20, font=FONT_ENTRY)
        if sem.get('end_date'):
            entry_ed.insert(0, str(sem['end_date']))
        entry_ed.pack(side="left")

        var_reg = tk.IntVar(value=sem['registration_open'])
        f_reg = tk.Frame(top)
        f_reg.pack(fill="x", padx=20, pady=5)
        tk.Checkbutton(f_reg, text="Mở đăng ký học kỳ", variable=var_reg, font=FONT_LABEL).pack(side="left")

        def save():
            name = entry_name.get().strip()
            ay_sel = var_ay.get()
            sd_s = entry_sd.get().strip()
            ed_s = entry_ed.get().strip()
            if not name or not ay_sel:
                messagebox.showerror("Error", "Điền đầy đủ thông tin", parent=top)
                return
            ay_id = ay_sel.split(" - ")[0]
            sd = sd_s or None
            ed = ed_s or None
            clear_sd = (entry_sd.get().strip() == "" and sem.get('start_date') is not None)
            clear_ed = (entry_ed.get().strip() == "" and sem.get('end_date') is not None)

            if sd:
                try:
                    datetime.strptime(sd, "%Y-%m-%d")
                except ValueError:
                    messagebox.showerror("Error", "Ngày BĐ không hợp lệ (YYYY-MM-DD)", parent=top)
                    return
            if ed:
                try:
                    datetime.strptime(ed, "%Y-%m-%d")
                except ValueError:
                    messagebox.showerror("Error", "Ngày KT không hợp lệ (YYYY-MM-DD)", parent=top)
                    return

            try:
                db.update_semester(
                    sid, registration_open=var_reg.get(), name=name,
                    academic_year_id=ay_id, start_date=sd, end_date=ed,
                    clear_start_date=clear_sd, clear_end_date=clear_ed
                )
                messagebox.showinfo("Success", "Đã cập nhật học kỳ", parent=top)
                top.destroy()
                self.refresh_all_admin_comboboxes()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=top)

        _make_btn(top, "Lưu thay đổi", save, bg=COLOR_PRIMARY, width=15).pack(pady=15)

    def update_semester_dates(self):
        item = self.sem_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một học kỳ trong bảng"); return
        sid = str(self.sem_tree.item(item[0])['values'][0])
        sd = self.sem_start_date.get().strip() or None
        ed = self.sem_end_date.get().strip() or None
        if sd:
            try:
                datetime.strptime(sd, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Error", "Ngày BĐ không hợp lệ (YYYY-MM-DD)"); return
        if ed:
            try:
                datetime.strptime(ed, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Error", "Ngày KT không hợp lệ (YYYY-MM-DD)"); return
        if sd and ed and sd > ed:
            messagebox.showerror("Error", "Ngày bắt đầu phải trước ngày kết thúc"); return
        try:
            db.update_semester(sid, start_date=sd, end_date=ed)
            messagebox.showinfo("Success", f"Đã cập nhật ngày cho HK {sid}")
            self.sem_start_date.delete(0, "end"); self.sem_end_date.delete(0, "end")
            self.refresh_academic()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def toggle_semester_reg(self):
        item = self.sem_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một học kỳ"); return
        sid = str(self.sem_tree.item(item[0])['values'][0])
        sem = db.get_semester(sid)
        if not sem:
            return
        new_val = 0 if sem['registration_open'] else 1
        db.update_semester(sid, registration_open=new_val)
        self.refresh_academic()
        status = "mở" if new_val else "đóng"
        messagebox.showinfo("Success", f"Đã {status} đăng ký cho HK {sid}")

    # ── BATCH & ADMIN CLASS ──────────────────────────────────────────────
    def build_batch_class(self, parent):
        tk.Label(parent, text="KHÓA TUYỂN SINH & LỚP HÀNH CHÍNH", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(20, 10))

        b_frame = tk.LabelFrame(parent, text="Thêm Khóa tuyển sinh", bg=COLOR_BG,
                                 fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=10)
        b_frame.pack(fill="x", padx=30, pady=5)
        tk.Label(b_frame, text="Mã:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5)
        self.batch_id = tk.Entry(b_frame, width=12, font=FONT_ENTRY); self.batch_id.grid(row=0, column=1, padx=5)
        tk.Label(b_frame, text="Tên:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5)
        self.batch_name = tk.Entry(b_frame, width=15, font=FONT_ENTRY); self.batch_name.grid(row=0, column=3, padx=5)
        tk.Label(b_frame, text="Năm:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=4, padx=5)
        self.batch_year = tk.Entry(b_frame, width=6, font=FONT_ENTRY); self.batch_year.grid(row=0, column=5, padx=5)
        _make_btn(b_frame, "Thêm", self.add_batch, width=8).grid(row=0, column=6, padx=5)
        _make_btn(b_frame, "Sửa", self.edit_batch, bg=COLOR_WARNING, width=6).grid(row=0, column=7, padx=5)

        ac_frame = tk.LabelFrame(parent, text="Thêm Lớp hành chính", bg=COLOR_BG,
                                  fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=10)
        ac_frame.pack(fill="x", padx=30, pady=5)
        tk.Label(ac_frame, text="Mã:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5)
        self.ac_id = tk.Entry(ac_frame, width=12, font=FONT_ENTRY); self.ac_id.grid(row=0, column=1, padx=5)
        tk.Label(ac_frame, text="Tên:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5)
        self.ac_name = tk.Entry(ac_frame, width=15, font=FONT_ENTRY); self.ac_name.grid(row=0, column=3, padx=5)
        tk.Label(ac_frame, text="Ngành:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=4, padx=5)
        self.ac_prog_var = tk.StringVar()
        self.ac_prog_cb = ttk.Combobox(ac_frame, textvariable=self.ac_prog_var, state="readonly", width=18)
        self.ac_prog_cb.grid(row=0, column=5, padx=5)
        tk.Label(ac_frame, text="Khóa:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=6, padx=5)
        self.ac_batch_var = tk.StringVar()
        self.ac_batch_cb = ttk.Combobox(ac_frame, textvariable=self.ac_batch_var, state="readonly", width=15)
        self.ac_batch_cb.grid(row=0, column=7, padx=5)
        _make_btn(ac_frame, "Thêm", self.add_admin_class, width=8).grid(row=0, column=8, padx=5)
        _make_btn(ac_frame, "Sửa", self.edit_admin_class, bg=COLOR_WARNING, width=6).grid(row=0, column=9, padx=5)

        cols_b = ("Mã", "Tên", "Năm")
        batch_frame = tk.Frame(parent)
        batch_frame.pack(fill="x", padx=30, pady=5)
        self.batch_tree = ttk.Treeview(batch_frame, columns=cols_b, show="headings", height=4)
        batch_scroll = ttk.Scrollbar(batch_frame, orient="vertical", command=self.batch_tree.yview)
        self.batch_tree.configure(yscrollcommand=batch_scroll.set)
        for c in cols_b: self.batch_tree.heading(c, text=c); self.batch_tree.column(c, width=180)
        self.batch_tree.pack(side="left", fill="x", expand=True)
        batch_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.batch_tree)

        cols_ac = ("Mã lớp", "Tên lớp", "Ngành", "Khóa")
        ac_frame = tk.Frame(parent)
        ac_frame.pack(fill="both", expand=True, padx=30, pady=5)
        self.ac_tree = ttk.Treeview(ac_frame, columns=cols_ac, show="headings", height=6)
        ac_scroll = ttk.Scrollbar(ac_frame, orient="vertical", command=self.ac_tree.yview)
        self.ac_tree.configure(yscrollcommand=ac_scroll.set)
        for c in cols_ac: self.ac_tree.heading(c, text=c); self.ac_tree.column(c, width=180)
        self.ac_tree.pack(side="left", fill="both", expand=True)
        ac_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.ac_tree)

        self.refresh_batch_class()

    def refresh_batch_class(self):
        for t in self.batch_tree.get_children(): self.batch_tree.delete(t)
        batches = db.list_admission_batches()
        for i, b in enumerate(batches):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.batch_tree.insert("", "end", values=(b['id'], b['name'], b['year']), tags=(tag,))
        self.ac_batch_cb['values'] = [f"{b['id']} - {b['name']}" for b in batches]

        progs = db.list_programs()
        self.ac_prog_cb['values'] = [f"{p['id']} - {p['name']}" for p in progs]

        for t in self.ac_tree.get_children(): self.ac_tree.delete(t)
        classes = db.list_admin_classes()
        for i, c in enumerate(classes):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.ac_tree.insert("", "end", values=(c['id'], c['name'], c.get('program_name', ''), c.get('batch_name', '')), tags=(tag,))
        check_empty_treeview(self.batch_tree, "Chưa có khóa tuyển sinh")
        check_empty_treeview(self.ac_tree, "Chưa có lớp hành chính")

    def add_batch(self):
        bid = self.batch_id.get().strip().upper()
        name = self.batch_name.get().strip()
        year_s = self.batch_year.get().strip()
        if not bid or not name or not year_s:
            messagebox.showerror("Error", "Điền đầy đủ thông tin"); return
        try:
            year = int(year_s)
        except ValueError:
            messagebox.showerror("Error", "Năm phải là số"); return
        try:
            db.add_admission_batch(bid, name, year)
            messagebox.showinfo("Success", f"Đã thêm khóa {bid}")
            self.batch_id.delete(0, "end"); self.batch_name.delete(0, "end"); self.batch_year.delete(0, "end")
            self.refresh_batch_class()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def edit_batch(self):
        item = self.batch_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một khóa để sửa"); return
        bid = str(self.batch_tree.item(item[0])['values'][0])
        batch = db.get_admission_batch(bid)
        if not batch:
            messagebox.showerror("Error", f"Khóa {bid} không tồn tại"); return

        top = tk.Toplevel(self.root)
        top.title(f"Sửa Khóa tuyển sinh - {bid}")
        top.geometry("400x240")
        top.grab_set()

        tk.Label(top, text=f"Mã khóa: {bid}", font=FONT_BODY_BOLD).pack(pady=(15, 10))

        f_name = tk.Frame(top)
        f_name.pack(fill="x", padx=20, pady=5)
        tk.Label(f_name, text="Tên khóa:", width=12, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_name = tk.Entry(f_name, width=28, font=FONT_ENTRY)
        entry_name.insert(0, batch['name'])
        entry_name.pack(side="left")

        f_yr = tk.Frame(top)
        f_yr.pack(fill="x", padx=20, pady=5)
        tk.Label(f_yr, text="Năm tuyển sinh:", width=12, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_yr = tk.Entry(f_yr, width=28, font=FONT_ENTRY)
        entry_yr.insert(0, str(batch['year']))
        entry_yr.pack(side="left")

        def save():
            name = entry_name.get().strip()
            year_s = entry_yr.get().strip()
            if not name or not year_s:
                messagebox.showerror("Error", "Điền đầy đủ thông tin", parent=top)
                return
            try:
                year = int(year_s)
            except ValueError:
                messagebox.showerror("Error", "Năm tuyển sinh phải là số", parent=top)
                return
            try:
                db.update_admission_batch(bid, name=name, year=year)
                messagebox.showinfo("Success", "Đã cập nhật khóa tuyển sinh", parent=top)
                top.destroy()
                self.refresh_all_admin_comboboxes()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=top)

        _make_btn(top, "Lưu thay đổi", save, bg=COLOR_PRIMARY, width=15).pack(pady=15)

    def add_admin_class(self):
        cid = self.ac_id.get().strip().upper()
        name = self.ac_name.get().strip()
        prog_sel = self.ac_prog_var.get()
        batch_sel = self.ac_batch_var.get()
        if not cid or not name or not prog_sel or not batch_sel:
            messagebox.showerror("Error", "Điền đầy đủ thông tin"); return
        prog_id = prog_sel.split(" - ")[0]
        batch_id = batch_sel.split(" - ")[0]
        try:
            db.add_admin_class(cid, name, prog_id, batch_id)
            messagebox.showinfo("Success", f"Đã thêm lớp {cid}")
            self.ac_id.delete(0, "end"); self.ac_name.delete(0, "end")
            self.refresh_batch_class()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def edit_admin_class(self):
        item = self.ac_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một lớp HC để sửa"); return
        cid = str(self.ac_tree.item(item[0])['values'][0])
        ac = db.get_admin_class(cid)
        if not ac:
            messagebox.showerror("Error", f"Lớp {cid} không tồn tại"); return

        top = tk.Toplevel(self.root)
        top.title(f"Sửa Lớp hành chính - {cid}")
        top.geometry("420x280")
        top.grab_set()

        tk.Label(top, text=f"Mã lớp HC: {cid}", font=FONT_BODY_BOLD).pack(pady=(15, 10))

        f_name = tk.Frame(top)
        f_name.pack(fill="x", padx=20, pady=5)
        tk.Label(f_name, text="Tên lớp:", width=12, anchor="w", font=FONT_LABEL).pack(side="left")
        entry_name = tk.Entry(f_name, width=28, font=FONT_ENTRY)
        entry_name.insert(0, ac['name'])
        entry_name.pack(side="left")

        f_prog = tk.Frame(top)
        f_prog.pack(fill="x", padx=20, pady=5)
        tk.Label(f_prog, text="Ngành:", width=12, anchor="w", font=FONT_LABEL).pack(side="left")
        progs = db.list_programs()
        prog_vals = [f"{p['id']} - {p['name']}" for p in progs]
        var_prog = tk.StringVar()
        cb_prog = ttk.Combobox(f_prog, textvariable=var_prog, values=prog_vals, state="readonly", width=26)
        curr_prog = next((v for v in prog_vals if v.startswith(str(ac['program_id']) + " -")), prog_vals[0] if prog_vals else "")
        var_prog.set(curr_prog)
        cb_prog.pack(side="left")

        f_batch = tk.Frame(top)
        f_batch.pack(fill="x", padx=20, pady=5)
        tk.Label(f_batch, text="Khóa:", width=12, anchor="w", font=FONT_LABEL).pack(side="left")
        batches = db.list_admission_batches()
        batch_vals = [f"{b['id']} - {b['name']}" for b in batches]
        var_batch = tk.StringVar()
        cb_batch = ttk.Combobox(f_batch, textvariable=var_batch, values=batch_vals, state="readonly", width=26)
        curr_batch = next((v for v in batch_vals if v.startswith(str(ac['batch_id']) + " -")), batch_vals[0] if batch_vals else "")
        var_batch.set(curr_batch)
        cb_batch.pack(side="left")

        def save():
            name = entry_name.get().strip()
            prog_sel = var_prog.get()
            batch_sel = var_batch.get()
            if not name or not prog_sel or not batch_sel:
                messagebox.showerror("Error", "Điền đầy đủ thông tin", parent=top)
                return
            prog_id = prog_sel.split(" - ")[0]
            batch_id = batch_sel.split(" - ")[0]
            try:
                db.update_admin_class(cid, name=name, program_id=prog_id, batch_id=batch_id)
                messagebox.showinfo("Success", "Đã cập nhật lớp hành chính", parent=top)
                top.destroy()
                self.refresh_all_admin_comboboxes()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=top)

        _make_btn(top, "Lưu thay đổi", save, bg=COLOR_PRIMARY, width=15).pack(pady=15)

    # ── SUBJECTS ─────────────────────────────────────────────────────────
    def build_subjects(self, parent):
        tk.Label(parent, text="DANH MỤC MÔN HỌC", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(20, 10))

        form = tk.LabelFrame(parent, text="Thêm Môn học", bg=COLOR_BG,
                              fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=10)
        form.pack(fill="x", padx=30, pady=5)
        tk.Label(form, text="Mã môn:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5)
        self.subj_id = tk.Entry(form, width=15, font=FONT_ENTRY); self.subj_id.grid(row=0, column=1, padx=5)
        tk.Label(form, text="Tên môn:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5)
        self.subj_name = tk.Entry(form, width=25, font=FONT_ENTRY); self.subj_name.grid(row=0, column=3, padx=5)
        tk.Label(form, text="Tín chỉ:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=4, padx=5)
        self.subj_credits = tk.Entry(form, width=5, font=FONT_ENTRY); self.subj_credits.grid(row=0, column=5, padx=5)
        _make_btn(form, "Thêm", self.add_subject, width=8).grid(row=0, column=6, padx=5)
        _make_btn(form, "Sửa", self.edit_subject, bg=COLOR_WARNING, width=6).grid(row=0, column=7, padx=5)

        btn_f = tk.Frame(parent, bg=COLOR_BG)
        btn_f.pack(pady=5)
        _make_btn(btn_f, "Xóa môn", self.delete_subject, bg=COLOR_DANGER, width=12).pack(side="left", padx=5)

        cols = ("Mã môn", "Tên môn", "Tín chỉ")
        subj_frame = tk.Frame(parent)
        subj_frame.pack(fill="both", expand=True, padx=30, pady=5)
        self.subj_tree = ttk.Treeview(subj_frame, columns=cols, show="headings")
        subj_scroll = ttk.Scrollbar(subj_frame, orient="vertical", command=self.subj_tree.yview)
        self.subj_tree.configure(yscrollcommand=subj_scroll.set)
        for c in cols: self.subj_tree.heading(c, text=c); self.subj_tree.column(c, width=200)
        self.subj_tree.pack(side="left", fill="both", expand=True)
        subj_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.subj_tree)
        self.refresh_subjects()

    def refresh_subjects(self):
        for t in self.subj_tree.get_children(): self.subj_tree.delete(t)
        for i, s in enumerate(db.list_subjects()):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.subj_tree.insert("", "end", values=(s['id'], s['name'], s['credits']), tags=(tag,))
        check_empty_treeview(self.subj_tree, "Chưa có môn học")

    def add_subject(self):
        sid = self.subj_id.get().strip().upper()
        name = self.subj_name.get().strip()
        cred_s = self.subj_credits.get().strip()
        if not sid or not name or not cred_s:
            messagebox.showerror("Error", "Điền đầy đủ thông tin môn học"); return
        try:
            credits = int(cred_s)
            if credits <= 0: raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Tín chỉ phải là số dương"); return
        try:
            db.add_subject(sid, name, credits)
            messagebox.showinfo("Success", f"Đã thêm môn {sid}")
            self.subj_id.delete(0, "end"); self.subj_name.delete(0, "end"); self.subj_credits.delete(0, "end")
            self.refresh_subjects()
            # Refresh section combos if they exist
            if hasattr(self, 'sec_subj_cb'):
                self._refresh_section_combos()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def edit_subject(self):
        item = self.subj_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một môn học để sửa"); return
        sid = str(self.subj_tree.item(item[0])['values'][0])
        old_name = str(self.subj_tree.item(item[0])['values'][1])
        new_name = simpledialog.askstring("Sửa Môn học", f"Tên mới cho {sid}:", initialvalue=old_name)
        if new_name is None:
            return
        new_cred = simpledialog.askinteger("Sửa Tín chỉ", f"Tín chỉ mới cho {sid}:",
                                            initialvalue=int(self.subj_tree.item(item[0])['values'][2]),
                                            minvalue=1, maxvalue=20)
        if new_cred is None:
            return
        try:
            db.update_subject(sid, name=new_name.strip() if new_name else None, credits=new_cred)
            messagebox.showinfo("Success", "Đã cập nhật")
            self.refresh_subjects()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def delete_subject(self):
        item = self.subj_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một môn học"); return
        sid = str(self.subj_tree.item(item[0])['values'][0])
        if messagebox.askyesno("Xác nhận", f"Xóa môn {sid}? Chỉ xóa được môn chưa có lớp HP."):
            try:
                services.delete_subject(db, sid)
                messagebox.showinfo("Success", "Đã xóa")
                self.refresh_subjects()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # ── CLASS SECTIONS ───────────────────────────────────────────────────
    def build_sections(self, parent):
        tk.Label(parent, text="QUẢN LÝ LỚP HỌC PHẦN", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(20, 5))

        # Filter
        filt = tk.Frame(parent, bg=COLOR_BG)
        filt.pack(fill="x", padx=30, pady=5)
        tk.Label(filt, text="Lọc theo HK:", bg=COLOR_BG, font=FONT_LABEL).pack(side="left", padx=5)
        self.sec_sem_var = tk.StringVar()
        self.sec_sem_cb = ttk.Combobox(filt, textvariable=self.sec_sem_var, state="readonly", width=30)
        self.sec_sem_cb.pack(side="left", padx=5)
        _make_btn(filt, "Lọc", self.refresh_sections, width=8).pack(side="left", padx=5)

        # Add form
        form = tk.LabelFrame(parent, text="Thêm Lớp HP", bg=COLOR_BG,
                              fg=COLOR_PRIMARY, font=FONT_BODY, padx=10, pady=8)
        form.pack(fill="x", padx=30, pady=5)

        tk.Label(form, text="Mã lớp HP:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=3, pady=3, sticky="w")
        self.sec_id = tk.Entry(form, width=15, font=FONT_ENTRY); self.sec_id.grid(row=0, column=1, padx=3, pady=3)
        tk.Label(form, text="Môn:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=3, pady=3, sticky="w")
        self.sec_subj_var = tk.StringVar()
        self.sec_subj_cb = ttk.Combobox(form, textvariable=self.sec_subj_var, state="readonly", width=20)
        self.sec_subj_cb.grid(row=0, column=3, padx=3, pady=3)
        tk.Label(form, text="HK:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=4, padx=3, pady=3, sticky="w")
        self.sec_sem2_var = tk.StringVar()
        self.sec_sem2_cb = ttk.Combobox(form, textvariable=self.sec_sem2_var, state="readonly", width=22)
        self.sec_sem2_cb.grid(row=0, column=5, padx=3, pady=3)

        tk.Label(form, text="GV:", bg=COLOR_BG, font=FONT_LABEL).grid(row=1, column=0, padx=3, pady=3, sticky="w")
        self.sec_lect = tk.Entry(form, width=15, font=FONT_ENTRY); self.sec_lect.grid(row=1, column=1, padx=3, pady=3)
        tk.Label(form, text="Sĩ số:", bg=COLOR_BG, font=FONT_LABEL).grid(row=1, column=2, padx=3, pady=3, sticky="w")
        self.sec_max = tk.Entry(form, width=6, font=FONT_ENTRY); self.sec_max.insert(0, "40"); self.sec_max.grid(row=1, column=3, padx=3, pady=3, sticky="w")
        tk.Label(form, text="Lịch (VD: Thu 2 7h-9h; Thu 4 13h-15h):", bg=COLOR_BG, font=FONT_LABEL).grid(row=1, column=4, padx=3, pady=3, sticky="w", columnspan=2)

        tk.Label(form, text="Lịch học:", bg=COLOR_BG, font=FONT_LABEL).grid(row=2, column=0, padx=3, pady=3, sticky="w")
        self.sec_sched = tk.Entry(form, width=50, font=FONT_ENTRY)
        self.sec_sched.grid(row=2, column=1, padx=3, pady=3, columnspan=4, sticky="w")
        _make_btn(form, "Thêm lớp HP", self.add_section, width=12).grid(row=2, column=5, padx=10, pady=3)

        # Buttons
        btn_f = tk.Frame(parent, bg=COLOR_BG)
        btn_f.pack(pady=5)
        _make_btn(btn_f, "Mở/Đóng ĐK", self.toggle_section_reg, bg=COLOR_WARNING, width=14).pack(side="left", padx=5)
        _make_btn(btn_f, "Sửa lớp HP", self.edit_section, bg=COLOR_WARNING, width=12).pack(side="left", padx=5)
        _make_btn(btn_f, "Xóa lớp HP", self.delete_section, bg=COLOR_DANGER, width=12).pack(side="left", padx=5)

        cols = ("Mã lớp", "Môn", "Học kỳ", "Giảng viên", "Lịch", "Sĩ số", "Đã ĐK", "Đăng ký")
        sec_frame = tk.Frame(parent)
        sec_frame.pack(fill="both", expand=True, padx=30, pady=5)
        self.sec_tree = ttk.Treeview(sec_frame, columns=cols, show="headings")
        sec_tree_scroll = ttk.Scrollbar(sec_frame, orient="vertical", command=self.sec_tree.yview)
        self.sec_tree.configure(yscrollcommand=sec_tree_scroll.set)
        for c in cols: self.sec_tree.heading(c, text=c); self.sec_tree.column(c, width=110)
        self.sec_tree.pack(side="left", fill="both", expand=True)
        sec_tree_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.sec_tree)

        self._refresh_section_combos()
        self.refresh_sections()

    def _refresh_section_combos(self):
        sems = db.list_semesters()
        vals = [_sem_cb_value(s) for s in sems]
        self.sec_sem_cb['values'] = ["Tất cả"] + vals
        self.sec_sem2_cb['values'] = vals
        subjs = db.list_subjects()
        self.sec_subj_cb['values'] = [f"{s['id']} - {s['name']}" for s in subjs]

    def refresh_sections(self):
        for t in self.sec_tree.get_children(): self.sec_tree.delete(t)
        sem_sel = self.sec_sem_var.get()
        sem_id = None
        if sem_sel and sem_sel != "Tất cả":
            sem_id = sem_sel.split(" - ")[0]
        sections = db.list_sections(semester_id=sem_id)
        for i, s in enumerate(sections):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            sched = _get_schedule_display(db, s['id'])
            enrolled = db.count_section_enrollments(s['id'])
            reg = "✅ Mở" if s['registration_open'] else "❌ Đóng"
            sem_display = f"{s.get('semester_name', '')} ({s.get('year_name', '')})"
            self.sec_tree.insert("", "end", values=(
                s['id'], s.get('subject_name', ''), sem_display,
                s.get('lecturer', ''), sched, s['max_students'], enrolled, reg
            ), tags=(tag,))
        check_empty_treeview(self.sec_tree, "Chưa có lớp học phần")

    def add_section(self):
        sid = self.sec_id.get().strip().upper()
        subj_sel = self.sec_subj_var.get()
        sem_sel = self.sec_sem2_var.get()
        lect = self.sec_lect.get().strip()
        max_s = self.sec_max.get().strip()
        sched_str = self.sec_sched.get().strip()

        if not sid or not subj_sel or not sem_sel:
            messagebox.showerror("Error", "Điền đầy đủ thông tin lớp HP"); return

        subj_id = subj_sel.split(" - ")[0]
        sem_id = sem_sel.split(" - ")[0]

        try:
            max_students = int(max_s) if max_s else 40
            if max_students <= 0: raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Sĩ số phải là số dương"); return

        if lect and not db.get_user("Lecturer", lect):
            messagebox.showerror("Error", "Giảng viên không tồn tại"); return

        schedules = []
        if sched_str:
            parsed = parse_multi_schedule(sched_str)
            if parsed is None:
                messagebox.showerror("Error", "Lịch không hợp lệ. VD: Thu 2 7h-9h; Thu 4 13h-15h"); return
            schedules = parsed

        try:
            services.create_class_section(db, sid, subj_id, sem_id, lect or None,
                                          max_students, schedules, TUITION_PER_CREDIT)
            if not schedules:
                messagebox.showinfo("Success", f"Đã thêm lớp HP {sid} (nháp — chưa có lịch, đóng ĐK)")
            else:
                messagebox.showinfo("Success", f"Đã thêm lớp HP {sid}")
            self.sec_id.delete(0, "end"); self.sec_sched.delete(0, "end"); self.sec_lect.delete(0, "end")
            self.refresh_sections()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def edit_section(self):
        item = self.sec_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một lớp HP để sửa"); return
        sid = str(self.sec_tree.item(item[0])['values'][0])
        section = db.get_section(sid)
        if not section:
            return
        enrolled = db.count_section_enrollments(sid)
        # Edit max_students
        new_max = simpledialog.askinteger("Sửa Sĩ số", f"Sĩ số tối đa cho {sid}:",
                                           initialvalue=section['max_students'], minvalue=1)
        if new_max is None:
            return
        try:
            services.update_class_section(db, sid, max_students=new_max)
            messagebox.showinfo("Success", "Đã cập nhật")
            self.refresh_sections()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def toggle_section_reg(self):
        item = self.sec_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một lớp HP"); return
        sid = str(self.sec_tree.item(item[0])['values'][0])
        section = db.get_section(sid)
        if not section:
            return
        new_val = 0 if section['registration_open'] else 1
        try:
            services.update_class_section(db, sid, registration_open=new_val)
            self.refresh_sections()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def delete_section(self):
        item = self.sec_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một lớp HP"); return
        sid = str(self.sec_tree.item(item[0])['values'][0])
        if messagebox.askyesno("Xác nhận", f"Xóa lớp HP {sid}?"):
            try:
                services.delete_class_section(db, sid)
                messagebox.showinfo("Success", "Đã xóa")
                self.refresh_sections()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # ── CREATE LECTURER ──────────────────────────────────────────────────
    def build_create_lecturer(self, parent):
        tk.Label(parent, text="TẠO TÀI KHOẢN GIẢNG VIÊN", font=FONT_TITLE, bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=30)
        lf = tk.LabelFrame(parent, text="Thông tin giảng viên", bg=COLOR_BG,
                           fg=COLOR_PRIMARY, font=FONT_BODY, padx=20, pady=15)
        lf.pack(pady=20, padx=60)
        tk.Label(lf, text="Username:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, pady=12, sticky="w")
        self.l_user = tk.Entry(lf, width=30, font=FONT_ENTRY); self.l_user.grid(row=0, column=1, padx=12, pady=12)
        tk.Label(lf, text="Password:", bg=COLOR_BG, font=FONT_LABEL).grid(row=1, column=0, pady=12, sticky="w")
        self.l_pass = tk.Entry(lf, width=30, font=FONT_ENTRY, show="*"); self.l_pass.grid(row=1, column=1, padx=12, pady=12)
        tk.Button(parent, text="TẠO TÀI KHOẢN", bg=COLOR_PRIMARY, fg="white", font=FONT_BTN_LG,
                  width=20, relief="flat", cursor="hand2",
                  activebackground=COLOR_TOPBAR, activeforeground="white",
                  command=self.create_lecturer).pack(pady=20)

    def create_lecturer(self):
        user = self.l_user.get().strip()
        pw = self.l_pass.get()
        if not user or not pw:
            messagebox.showerror("Error", "Điền đầy đủ thông tin"); return
        if db.get_user("Lecturer", user):
            messagebox.showerror("Error", "Tài khoản đã tồn tại"); return
        try:
            db.create_lecturer(user, pw)
            messagebox.showinfo("Success", f"Đã tạo giảng viên {user}")
            self.l_user.delete(0, "end"); self.l_pass.delete(0, "end")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── STUDENTS ─────────────────────────────────────────────────────────
    # ── STUDENTS ─────────────────────────────────────────────────────────
    def build_students(self, parent):
        tk.Label(parent, text="QUẢN LÝ SINH VIÊN", font=FONT_TITLE, bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(15, 5))

        # Filter and Search bar
        filter_f = tk.LabelFrame(parent, text="Tìm kiếm & Bộ lọc", bg=COLOR_BG, fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=8)
        filter_f.pack(fill="x", padx=30, pady=5)
        
        # Row 1: Search & Status
        tk.Label(filter_f, text="🔍 Tìm (MSSV/Tên):", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5, sticky="w")
        self.st_search_var = tk.StringVar()
        tk.Entry(filter_f, textvariable=self.st_search_var, width=20, font=FONT_ENTRY).grid(row=0, column=1, padx=5)
        
        tk.Label(filter_f, text="Trạng thái:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5, sticky="w")
        self.st_status_var = tk.StringVar()
        self.st_status_cb = ttk.Combobox(filter_f, textvariable=self.st_status_var, state="readonly", width=15)
        self.st_status_cb['values'] = ["(Tất cả)", "Đang học", "Bảo lưu", "Thôi học", "Tốt nghiệp"]
        self.st_status_cb.current(0)
        self.st_status_cb.grid(row=0, column=3, padx=5)

        tk.Label(filter_f, text="Khoa:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=4, padx=5, sticky="w")
        self.st_dept_var = tk.StringVar()
        self.st_dept_cb = ttk.Combobox(filter_f, textvariable=self.st_dept_var, state="readonly", width=15)
        self.st_dept_cb.grid(row=0, column=5, padx=5)
        self.st_dept_cb.bind("<<ComboboxSelected>>", self._on_dept_filter_change)

        _make_btn(filter_f, "Lọc / Tìm", self.search_students, width=8).grid(row=0, column=6, padx=10)
        _make_btn(filter_f, "Xóa lọc", self.clear_filters_and_search, width=8, bg=COLOR_WARNING).grid(row=0, column=7, padx=5)

        # Row 2: Program, Batch, Admin Class
        tk.Label(filter_f, text="Ngành:", bg=COLOR_BG, font=FONT_LABEL).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.st_prog_var = tk.StringVar()
        self.st_prog_cb = ttk.Combobox(filter_f, textvariable=self.st_prog_var, state="readonly", width=20)
        self.st_prog_cb.grid(row=1, column=1, padx=5, pady=5)
        self.st_prog_cb.bind("<<ComboboxSelected>>", self._on_prog_filter_change)

        tk.Label(filter_f, text="Khóa TS:", bg=COLOR_BG, font=FONT_LABEL).grid(row=1, column=2, padx=5, pady=5, sticky="w")
        self.st_batch_var = tk.StringVar()
        self.st_batch_cb = ttk.Combobox(filter_f, textvariable=self.st_batch_var, state="readonly", width=15)
        self.st_batch_cb.grid(row=1, column=3, padx=5, pady=5)
        self.st_batch_cb.bind("<<ComboboxSelected>>", self._on_batch_filter_change)

        tk.Label(filter_f, text="Lớp HC:", bg=COLOR_BG, font=FONT_LABEL).grid(row=1, column=4, padx=5, pady=5, sticky="w")
        self.st_class_filter_var = tk.StringVar()
        self.st_class_filter_cb = ttk.Combobox(filter_f, textvariable=self.st_class_filter_var, state="readonly", width=15)
        self.st_class_filter_cb.grid(row=1, column=5, padx=5, pady=5)

        # Create student (Collapsed into a smaller line or button if space is tight, but we keep it)
        form = tk.LabelFrame(parent, text="Tạo tài khoản sinh viên", bg=COLOR_BG, fg=COLOR_PRIMARY, font=FONT_BODY, padx=15, pady=8)
        form.pack(fill="x", padx=30, pady=5)
        tk.Label(form, text="Username:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=0, padx=5, sticky="w")
        self.st_user = tk.Entry(form, width=15, font=FONT_ENTRY); self.st_user.grid(row=0, column=1, padx=5)
        tk.Label(form, text="Password:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=2, padx=5, sticky="w")
        self.st_pass = tk.Entry(form, width=15, font=FONT_ENTRY, show="*"); self.st_pass.grid(row=0, column=3, padx=5)
        tk.Label(form, text="Lớp HC:", bg=COLOR_BG, font=FONT_LABEL).grid(row=0, column=4, padx=5, sticky="w")
        self.st_class_var = tk.StringVar()
        self.st_class_cb = ttk.Combobox(form, textvariable=self.st_class_var, state="readonly", width=18)
        self.st_class_cb.grid(row=0, column=5, padx=5)
        _make_btn(form, "Tạo SV", self.create_student, width=10).grid(row=0, column=6, padx=10)

        # Buttons
        btn_f = tk.Frame(parent, bg=COLOR_BG)
        btn_f.pack(pady=5)
        _make_btn(btn_f, "Xem hồ sơ", self.view_student_profile, bg=COLOR_PRIMARY, width=18).pack(side="left", padx=5)
        _make_btn(btn_f, "Đổi trạng thái", self.change_student_status_dialog, bg=COLOR_WARNING, width=14).pack(side="left", padx=5)
        _make_btn(btn_f, "Xuất CSV", self.export_students_csv, bg=COLOR_SUCCESS, width=10).pack(side="left", padx=5)
        _make_btn(btn_f, "Sửa thông tin", self.edit_student, bg=COLOR_WARNING, width=12).pack(side="left", padx=5)
        _make_btn(btn_f, "Gán lớp HC", self.assign_class, bg=COLOR_WARNING, width=10).pack(side="left", padx=5)
        _make_btn(btn_f, "Đổi mật khẩu", self.change_pw, bg=COLOR_WARNING, width=12).pack(side="left", padx=5)
        _make_btn(btn_f, "Xóa SV", self.delete_student, bg=COLOR_DANGER, width=8).pack(side="left", padx=5)

        self.st_count_label = tk.Label(parent, text="Số kết quả: 0", bg=COLOR_BG, font=FONT_LABEL, fg=COLOR_PRIMARY)
        self.st_count_label.pack(anchor="w", padx=30)

        cols = ("Username", "MSSV", "Tên", "Giới tính", "Lớp HC", "Ngành", "Trạng thái")
        st_frame = tk.Frame(parent)
        st_frame.pack(fill="both", expand=True, padx=30, pady=5)
        self.st_tree = ttk.Treeview(st_frame, columns=cols, show="headings")
        st_scroll = ttk.Scrollbar(st_frame, orient="vertical", command=self.st_tree.yview)
        self.st_tree.configure(yscrollcommand=st_scroll.set)
        for c in cols: self.st_tree.heading(c, text=c); self.st_tree.column(c, width=110)
        self.st_tree.pack(side="left", fill="both", expand=True)
        st_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.st_tree)

        # Pagination controls
        page_f = tk.Frame(parent, bg=COLOR_BG)
        page_f.pack(pady=5)
        self.st_page = 1
        self.st_limit = 50
        _make_btn(page_f, "Trang trước", self.prev_page_st, width=10).pack(side="left", padx=5)
        self.st_page_label = tk.Label(page_f, text="Trang 1", bg=COLOR_BG, font=FONT_LABEL)
        self.st_page_label.pack(side="left", padx=10)
        _make_btn(page_f, "Trang sau", self.next_page_st, width=10).pack(side="left", padx=5)

        self.refresh_students()

    def _on_dept_filter_change(self, event=None):
        dept_sel = self.st_dept_var.get()
        if not dept_sel or dept_sel == "(Tất cả)":
            self.st_prog_cb['values'] = ["(Tất cả)"] + [f"{p['id']} - {p['name']}" for p in db.list_programs()]
        else:
            dept_id = dept_sel.split(" - ")[0]
            progs = [p for p in db.list_programs() if str(p.get('department_id')) == str(dept_id)]
            self.st_prog_cb['values'] = ["(Tất cả)"] + [f"{p['id']} - {p['name']}" for p in progs]
        self.st_prog_var.set("(Tất cả)")
        self._update_class_filter_combobox()

    def _on_prog_filter_change(self, event=None):
        self._update_class_filter_combobox()

    def _on_batch_filter_change(self, event=None):
        self._update_class_filter_combobox()

    def _update_class_filter_combobox(self):
        dept_sel = self.st_dept_var.get()
        prog_sel = self.st_prog_var.get()
        batch_sel = self.st_batch_var.get()
        classes = db.list_admin_classes()
        
        if dept_sel and dept_sel != "(Tất cả)":
            dept_id = dept_sel.split(" - ")[0]
            classes = [c for c in classes if str(c.get('department_id', '')) == str(dept_id)]
            
        if prog_sel and prog_sel != "(Tất cả)":
            prog_id = prog_sel.split(" - ")[0]
            classes = [c for c in classes if str(c.get('program_id')) == str(prog_id)]
            
        if batch_sel and batch_sel != "(Tất cả)":
            batch_id = batch_sel.split(" - ")[0]
            classes = [c for c in classes if str(c.get('batch_id')) == str(batch_id)]
            
        old_val = self.st_class_filter_var.get()
        new_values = ["(Tất cả)"] + [f"{c['id']} - {c['name']}" for c in classes]
        self.st_class_filter_cb['values'] = new_values
        
        if old_val in new_values:
            self.st_class_filter_var.set(old_val)
        else:
            self.st_class_filter_var.set("(Tất cả)")

    def clear_filters_and_search(self):
        self.st_search_var.set("")
        self.st_status_var.set("(Tất cả)")
        self.st_dept_var.set("(Tất cả)")
        
        # Restore full prog/class list
        self.st_prog_cb['values'] = ["(Tất cả)"] + [f"{p['id']} - {p['name']}" for p in db.list_programs()]
        self.st_prog_var.set("(Tất cả)")
        self.st_batch_var.set("(Tất cả)")
        
        self.st_class_filter_cb['values'] = ["(Tất cả)"] + [f"{c['id']} - {c['name']}" for c in db.list_admin_classes()]
        self.st_class_filter_var.set("(Tất cả)")
        
        self.st_page = 1
        self.refresh_students()

    def search_students(self):
        self.st_page = 1
        self._load_students()

    def _get_current_student_filters(self):
        filters = {}
        status = self.st_status_var.get()
        if status and status != "(Tất cả)": filters['academic_status'] = status
        
        dept = self.st_dept_var.get()
        if dept and dept != "(Tất cả)": filters['department_id'] = dept.split(" - ")[0]
        
        prog = self.st_prog_var.get()
        if prog and prog != "(Tất cả)": filters['program_id'] = prog.split(" - ")[0]
        
        batch = self.st_batch_var.get()
        if batch and batch != "(Tất cả)": filters['batch_id'] = batch.split(" - ")[0]
        
        cls = self.st_class_filter_var.get()
        if cls and cls != "(Tất cả)": filters['admin_class_id'] = cls.split(" - ")[0]
        
        return filters

    def _load_students(self):
        search_term = self.st_search_var.get().strip()
        filters = self._get_current_student_filters()
        
        # Populate form combobox
        classes = db.list_admin_classes()
        self.st_class_cb['values'] = ["(Chưa phân)"] + [f"{c['id']} - {c['name']}" for c in classes]

        # Populate filter comboboxes if they are empty
        if not self.st_dept_cb['values']:
            self.st_dept_cb['values'] = ["(Tất cả)"] + [f"{d['id']} - {d['name']}" for d in db.list_departments()]
            self.st_prog_cb['values'] = ["(Tất cả)"] + [f"{p['id']} - {p['name']}" for p in db.list_programs()]
            self.st_batch_cb['values'] = ["(Tất cả)"] + [f"{b['id']} - {b['name']}" for b in db.list_admission_batches()]
            self.st_class_filter_cb['values'] = ["(Tất cả)"] + [f"{c['id']} - {c['name']}" for c in classes]

        total_count = db.count_students(search=search_term, filters=filters)
        self.st_count_label.config(text=f"Số kết quả: {total_count}")

        # Adjust page if result set is smaller
        max_page = max(1, (total_count + self.st_limit - 1) // self.st_limit)
        if self.st_page > max_page:
            self.st_page = max_page

        offset = (self.st_page - 1) * self.st_limit
        rows = db.list_students(search=search_term, filters=filters, limit=self.st_limit, offset=offset)

        for t in self.st_tree.get_children(): self.st_tree.delete(t)
        for i, r in enumerate(rows):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.st_tree.insert("", "end", values=(
                r['username'], r['mssv'], r.get('name', ''), r.get('gender', ''),
                r.get('class_name', '—'), r.get('program_name', '—'),
                r.get('academic_status', 'Đang học')
            ), tags=(tag,))
        check_empty_treeview(self.st_tree, "Không tìm thấy sinh viên")
        self.st_page_label.config(text=f"Trang {self.st_page}")

    def prev_page_st(self):
        if self.st_page > 1:
            self.st_page -= 1
            self._load_students()

    def next_page_st(self):
        search_term = self.st_search_var.get().strip()
        filters = self._get_current_student_filters()
        total_count = db.count_students(search=search_term, filters=filters)
        max_page = max(1, (total_count + self.st_limit - 1) // self.st_limit)
        if self.st_page < max_page:
            self.st_page += 1
            self._load_students()

    def refresh_students(self):
        self._load_students()

    def create_student(self):
        user = self.st_user.get().strip()
        pw = self.st_pass.get()
        if not user or not pw:
            messagebox.showerror("Error", "Điền username và password"); return
        if db.get_user("Student", user):
            messagebox.showerror("Error", "Tài khoản đã tồn tại"); return
        try:
            mssv = db.add_student(user, pw)
            # Assign admin class if selected
            class_sel = self.st_class_var.get()
            if class_sel and class_sel != "(Chưa phân)":
                class_id = class_sel.split(" - ")[0]
                services.assign_admin_class(db, user, class_id)
            messagebox.showinfo("Success", f"Đã tạo SV {user} (MSSV: {mssv})")
            self.st_user.delete(0, "end"); self.st_pass.delete(0, "end")
            self.refresh_students()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def edit_student(self):
        item = self.st_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một sinh viên để sửa"); return
        username = str(self.st_tree.item(item[0])['values'][0])
        user = db.get_user("Student", username)
        if not user:
            return

        # Edit dialog
        win = tk.Toplevel(self.root)
        win.title(f"Sửa hồ sơ — {username}")
        win.geometry("420x350")
        win.configure(bg=COLOR_BG)
        win.grab_set()

        fields = {
            "Họ tên": tk.StringVar(value=user.get('name', '') or ''),
            "Giới tính": tk.StringVar(value=user.get('gender', '') or ''),
            "Email": tk.StringVar(value=user.get('email', '') or ''),
            "Điện thoại": tk.StringVar(value=user.get('phone', '') or ''),
            "Địa chỉ": tk.StringVar(value=user.get('address', '') or ''),
        }
        entries = {}
        for i, (label, var) in enumerate(fields.items()):
            tk.Label(win, text=f"{label}:", bg=COLOR_BG, font=FONT_LABEL).grid(row=i, column=0, padx=15, pady=8, sticky="w")
            e = tk.Entry(win, textvariable=var, font=FONT_ENTRY, width=30)
            e.grid(row=i, column=1, padx=15, pady=8)
            entries[label] = e

        # Admin class combobox
        tk.Label(win, text="Lớp HC:", bg=COLOR_BG, font=FONT_LABEL).grid(row=len(fields), column=0, padx=15, pady=8, sticky="w")
        cls_var = tk.StringVar()
        classes = db.list_admin_classes()
        cls_values = ["(Không phân)"] + [f"{c['id']} - {c['name']}" for c in classes]
        cls_cb = ttk.Combobox(win, textvariable=cls_var, state="readonly", width=28, values=cls_values)
        cls_cb.grid(row=len(fields), column=1, padx=15, pady=8)
        # Set current
        current_cls = user.get('admin_class_id')
        if current_cls:
            for v in cls_values:
                if v.startswith(f"{current_cls} -"):
                    cls_var.set(v); break
        else:
            cls_var.set("(Không phân)")

        def save():
            name = fields["Họ tên"].get().strip()
            gender = fields["Giới tính"].get().strip()
            email = fields["Email"].get().strip()
            phone = fields["Điện thoại"].get().strip()
            address = fields["Địa chỉ"].get().strip()
            cls_sel = cls_var.get()
            cls_id = None
            if cls_sel and cls_sel != "(Không phân)":
                cls_id = cls_sel.split(" - ")[0]
            try:
                db.update_student_profile(username, name=name, gender=gender,
                                          email=email, phone=phone, address=address,
                                          admin_class_id=cls_id)
                messagebox.showinfo("Success", "Đã cập nhật hồ sơ")
                win.destroy()
                self.refresh_students()
            except Exception as e:
                messagebox.showerror("Error", str(e))

        _make_btn(win, "Lưu", save, width=12).grid(row=len(fields)+1, column=1, pady=15, sticky="e", padx=15)

    def assign_class(self):
        item = self.st_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một sinh viên"); return
        username = str(self.st_tree.item(item[0])['values'][0])
        classes = db.list_admin_classes()
        choices = ["(Bỏ gán)"] + [f"{c['id']} - {c['name']}" for c in classes]
        sel = simpledialog.askstring("Gán lớp HC", f"Chọn lớp cho {username}:\n" + "\n".join(choices))
        if sel is None:
            return
        if sel == "(Bỏ gán)" or not sel.strip():
            class_id = None
        else:
            class_id = sel.strip().split(" - ")[0]
        try:
            services.assign_admin_class(db, username, class_id)
            messagebox.showinfo("Success", "Đã cập nhật")
            self.refresh_students()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def change_pw(self):
        item = self.st_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một sinh viên"); return
        username = str(self.st_tree.item(item[0])['values'][0])
        new_pw = simpledialog.askstring("Đổi mật khẩu", f"Mật khẩu mới cho {username}:")
        if not new_pw or not new_pw.strip():
            return
        from .database import hash_password
        hashed = hash_password(new_pw.strip())
        db.cursor.execute("UPDATE students SET password=%s WHERE username=%s", (hashed, username))
        db.conn.commit()
        messagebox.showinfo("Success", "Đã đổi mật khẩu")

    def delete_student(self):
        item = self.st_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một sinh viên"); return
        username = str(self.st_tree.item(item[0])['values'][0])
        if messagebox.askyesno("Xác nhận", f"Xóa SV {username}? Chỉ xóa được hồ sơ chưa có lịch sử."):
            try:
                services.delete_student(db, username)
                messagebox.showinfo("Success", "Đã xóa")
                self.refresh_students()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def export_students_csv(self):
        search_term = self.st_search_var.get().strip()
        filters = self._get_current_student_filters()
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Lưu danh sách sinh viên"
        )
        if not file_path:
            return
            
        try:
            count = services.export_students_csv(db, search_term, filters, file_path)
            if count == 0:
                messagebox.showinfo("Info", "Không có dữ liệu để xuất")
            else:
                messagebox.showinfo("Success", f"Đã xuất {count} sinh viên ra file CSV")
        except Exception as e:
            messagebox.showerror("Error", f"Lỗi khi xuất CSV: {e}")

    def change_student_status_dialog(self):
        item = self.st_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một sinh viên")
            return
        mssv = str(self.st_tree.item(item[0])['values'][1])
        curr_status = str(self.st_tree.item(item[0])['values'][6])
        
        top = tk.Toplevel(self.root)
        top.title(f"Đổi trạng thái - {mssv}")
        top.geometry("400x250")
        top.grab_set()
        
        tk.Label(top, text=f"Trạng thái hiện tại: {curr_status}", font=FONT_LABEL).pack(pady=10)
        
        f1 = tk.Frame(top)
        f1.pack(pady=5)
        tk.Label(f1, text="Trạng thái mới:", font=FONT_LABEL).pack(side="left")
        var_status = tk.StringVar(value=curr_status)
        cb = ttk.Combobox(f1, textvariable=var_status, state="readonly", width=15)
        cb['values'] = ["Đang học", "Bảo lưu", "Thôi học", "Tốt nghiệp"]
        cb.pack(side="left", padx=5)
        
        f2 = tk.Frame(top)
        f2.pack(pady=5)
        tk.Label(f2, text="Lý do:", font=FONT_LABEL).pack(side="left")
        entry_reason = tk.Entry(f2, width=30, font=FONT_ENTRY)
        entry_reason.pack(side="left", padx=5)
        
        def save():
            new_st = var_status.get()
            reason = entry_reason.get()
            try:
                services.change_student_status(db, mssv, new_st, reason)
                messagebox.showinfo("Success", "Đã đổi trạng thái thành công", parent=top)
                top.destroy()
                self.refresh_students()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=top)
                
        _make_btn(top, "Lưu", save, width=10).pack(pady=15)

    def view_student_profile(self):
        item = self.st_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một sinh viên")
            return
        mssv = str(self.st_tree.item(item[0])['values'][1])
        
        prof = db.get_student_profile(mssv)
        if not prof:
            messagebox.showerror("Error", "Không tìm thấy hồ sơ")
            return
            
        top = tk.Toplevel(self.root)
        top.title(f"Hồ sơ tổng hợp - {mssv}")
        top.geometry("800x600")
        
        # Info frame
        info_f = tk.LabelFrame(top, text="Thông tin chung", font=FONT_LABEL, padx=10, pady=10)
        info_f.pack(fill="x", padx=10, pady=10)
        
        i = prof['info']
        tk.Label(info_f, text=f"Họ tên: {i.get('name', '')}").grid(row=0, column=0, sticky="w", padx=10)
        tk.Label(info_f, text=f"MSSV: {i['mssv']}").grid(row=0, column=1, sticky="w", padx=10)
        tk.Label(info_f, text=f"Lớp HC: {i.get('class_name', '')}").grid(row=1, column=0, sticky="w", padx=10)
        tk.Label(info_f, text=f"Ngành: {i.get('program_name', '')}").grid(row=1, column=1, sticky="w", padx=10)
        tk.Label(info_f, text=f"Khoa: {i.get('department_name', '')}").grid(row=2, column=0, sticky="w", padx=10)
        tk.Label(info_f, text=f"Khóa: {i.get('batch_name', '')}").grid(row=2, column=1, sticky="w", padx=10)
        tk.Label(info_f, text=f"Trạng thái: {i.get('academic_status', 'Đang học')}", fg=COLOR_PRIMARY, font=("Segoe UI", 11, "bold")).grid(row=3, column=0, sticky="w", padx=10, pady=5)
        
        # Notebook for tabs
        nb = ttk.Notebook(top)
        nb.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Tab 1: Enrollments & Grades
        tab_eg = tk.Frame(nb)
        nb.add(tab_eg, text="Học tập & Điểm")
        
        cols_eg = ("Học kỳ", "Mã HP", "Môn học", "TC", "Giữa kỳ", "Cuối kỳ")
        tree_eg = ttk.Treeview(tab_eg, columns=cols_eg, show="headings")
        for c in cols_eg: tree_eg.heading(c, text=c)
        tree_eg.column("Học kỳ", width=120)
        tree_eg.column("TC", width=40)
        tree_eg.pack(fill="both", expand=True, padx=5, pady=5)
        
        for en in prof['enrollments']:
            g = prof['grades'].get(en['enrollment_id'], {})
            tree_eg.insert("", "end", values=(
                f"{en['semester_name']} ({en['academic_year_name']})",
                en['section_id'],
                en['subject_name'],
                en['credits'],
                g.get('midterm', ''),
                g.get('final_score', '')
            ))
            
        # Tab 2: Payments
        tab_p = tk.Frame(nb)
        nb.add(tab_p, text="Thanh toán")
        
        cols_p = ("Ngày", "Mã HP", "Số tiền", "Trạng thái")
        tree_p = ttk.Treeview(tab_p, columns=cols_p, show="headings")
        for c in cols_p: tree_p.heading(c, text=c)
        tree_p.pack(fill="both", expand=True, padx=5, pady=5)
        
        # We need to map payment to section_id
        # We can create a mapping from enrollment_id to section_id
        en_map = {e['enrollment_id']: e['section_id'] for e in prof['enrollments']}
        for p in prof['payments']:
            tree_p.insert("", "end", values=(
                p['time'],
                en_map.get(p['enrollment_id'], ''),
                f"{p['amount']:,.0f}",
                p['status']
            ))
            
        # Tab 3: History
        tab_h = tk.Frame(nb)
        nb.add(tab_h, text="Lịch sử trạng thái")
        
        cols_h = ("Ngày", "Từ", "Sang", "Lý do", "Người đổi")
        tree_h = ttk.Treeview(tab_h, columns=cols_h, show="headings")
        for c in cols_h: tree_h.heading(c, text=c)
        tree_h.pack(fill="both", expand=True, padx=5, pady=5)
        
        for h in prof['history']:
            tree_h.insert("", "end", values=(
                h['changed_at'],
                h['old_status'],
                h['new_status'],
                h['reason'],
                h['changed_by']
            ))


# ═══════════════════════════════════════════════════════════════════════════
# STUDENT DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

class StudentDashboard:
    def __init__(self, username):
        self.username = username
        user = db.get_user("Student", username)
        if not user:
            messagebox.showerror("Lỗi", "Không tìm thấy sinh viên"); return
        self.mssv = user['mssv']

        self.root = tk.Tk()
        self.root.protocol("WM_DELETE_WINDOW", lambda: _close_session_window(self.root))
        self.root.title(f"Sinh viên - {user.get('name', username)} ({self.mssv})")
        self.root.geometry("1250x750")
        self.root.minsize(1024, 600)
        self.root.resizable(True, True)
        self.root.configure(bg=COLOR_BG)

        sidebar = tk.Frame(self.root, bg=COLOR_TOPBAR, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="🎓 Sinh viên", font=("Segoe UI", 10),
                 bg=COLOR_TOPBAR, fg="#B2DFDB").pack(pady=(18, 2))
        tk.Label(sidebar, text=f"{user.get('name', username)}", font=("Segoe UI", 13, "bold"),
                 bg=COLOR_TOPBAR, fg="white").pack()
        tk.Label(sidebar, text=f"MSSV: {self.mssv}", font=("Segoe UI", 9),
                 bg=COLOR_TOPBAR, fg="#B2DFDB").pack(pady=(2, 18))
        tk.Frame(sidebar, bg="#1A8A8D", height=1).pack(fill="x", padx=15, pady=(0, 10))

        menu_items = [
            "📊  Tổng quan",
            "📚  Đăng ký môn học",
            "📅  Thời khóa biểu",
            "📊  Bảng điểm",
            "👤  Hồ sơ cá nhân",
            "💳  Học phí",
        ]

        self.sidebar_buttons = []
        for i, text in enumerate(menu_items):
            btn = tk.Button(sidebar, text=text, font=("Segoe UI", 11),
                            bg=COLOR_TOPBAR, fg="white", relief="flat",
                            anchor="w", padx=18, pady=10, cursor="hand2",
                            activebackground=COLOR_PRIMARY, activeforeground="white",
                            command=lambda idx=i: self._show_page(idx))
            btn.pack(fill="x")
            self.sidebar_buttons.append(btn)

        tk.Frame(sidebar, bg=COLOR_TOPBAR).pack(fill="both", expand=True)
        tk.Button(sidebar, text="🚪  Đăng xuất", font=FONT_BTN,
                  bg=COLOR_DANGER, fg="white", relief="flat", cursor="hand2", pady=10,
                  activebackground="#C13639", activeforeground="white",
                  command=self.logout).pack(fill="x", padx=12, pady=15)

        content = tk.Frame(self.root, bg=COLOR_BG)
        content.pack(side="right", fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.pages = []
        page_builders = [
            self.build_overview,
            self.build_registration,
            self.build_schedule,
            self.build_grades,
            self.build_profile,
            self.build_payments,
        ]
        for builder in page_builders:
            page = tk.Frame(content, bg=COLOR_BG)
            page.grid(row=0, column=0, sticky="nsew")
            builder(page)
            self.pages.append(page)

        self._show_page(0)
        self.root.mainloop()

    def _show_page(self, index):
        self.pages[index].tkraise()
        for i, btn in enumerate(self.sidebar_buttons):
            if i == index:
                btn.config(bg=COLOR_PRIMARY, font=("Segoe UI", 11, "bold"))
            else:
                btn.config(bg=COLOR_TOPBAR, font=("Segoe UI", 11))

    def logout(self):
        if messagebox.askyesno("Đăng xuất", "Bạn có chắc muốn đăng xuất?"):
            from .session import session
            session.logout()
            self.root.destroy()
            LoginWindow()

    # ── OVERVIEW ─────────────────────────────────────────────────────────
    def build_overview(self, parent):
        user = db.get_user("Student", self.username)
        name = user['name'] if user and user.get('name') else self.username

        tk.Label(parent, text=f"Xin chào, {name} – MSSV: {self.mssv}",
                 font=FONT_TITLE, bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(20, 10))

        # Show admin class info
        students = db.list_students()
        my_info = next((s for s in students if s['username'] == self.username), None)
        info_text = ""
        if my_info:
            cls = my_info.get('class_name', '—')
            prog = my_info.get('program_name', '—')
            batch = my_info.get('batch_name', '—')
            info_text = f"Lớp: {cls}  |  Ngành: {prog}  |  Khóa: {batch}"
        tk.Label(parent, text=info_text, font=FONT_BODY, bg=COLOR_BG, fg="#6B7280").pack(pady=(0, 15))

        cards = tk.Frame(parent, bg=COLOR_BG)
        cards.pack(padx=30, pady=10)
        for c in range(3):
            cards.grid_columnconfigure(c, weight=1)

        enrolled_count = len(db.get_enrollments(self.mssv))
        _make_card(cards, "Số lớp đã đăng ký", enrolled_count, 0)

        grades = db.get_grades(self.mssv)
        valid = [(g['midterm'] + g['final_score']) / 2
                 for g in grades
                 if g.get('midterm') is not None and g.get('final_score') is not None]
        gpa_str = f"{sum(valid) / len(valid):.2f}" if valid else "Chưa có dữ liệu"
        _make_card(cards, "Điểm trung bình", gpa_str, 1)

        payments = db.list_payments(self.mssv)
        total_paid = sum(float(p['amount']) for p in payments if p.get('status') == 'Paid')
        _make_card(cards, "Đã thanh toán", f"{total_paid:,.0f} đ", 2, accent=COLOR_SUCCESS)

    # ── REGISTRATION ─────────────────────────────────────────────────────
    def build_registration(self, parent):
        tk.Label(parent, text="ĐĂNG KÝ MÔN HỌC", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(15, 5))

        filt = tk.Frame(parent, bg=COLOR_BG)
        filt.pack(fill="x", padx=20, pady=5)
        tk.Label(filt, text="Chọn học kỳ:", bg=COLOR_BG, font=FONT_LABEL).pack(side="left", padx=5)
        self.reg_sem_var = tk.StringVar()
        self.reg_sem_cb = ttk.Combobox(filt, textvariable=self.reg_sem_var, state="readonly", width=35)
        self.reg_sem_cb.pack(side="left", padx=5)
        _make_btn(filt, "Tải danh sách", self.refresh_registration, width=14).pack(side="left", padx=5)

        # Populate semester list
        sems = db.list_semesters()
        open_sems = [s for s in sems if s['registration_open']]
        self.reg_sem_cb['values'] = [_sem_cb_value(s) for s in open_sems]

        tk.Label(parent, text="Double-click để đăng ký", font=("Segoe UI", 10), bg=COLOR_BG, fg="#888").pack()

        cols = ("Mã lớp HP", "Mã môn", "Tên môn", "Giảng viên", "Lịch học", "TC", "Sĩ số", "Còn chỗ")
        reg_frame = tk.Frame(parent)
        reg_frame.pack(fill="both", expand=True, padx=20, pady=8)
        self.reg_tree = ttk.Treeview(reg_frame, columns=cols, show="headings")
        reg_scroll = ttk.Scrollbar(reg_frame, orient="vertical", command=self.reg_tree.yview)
        self.reg_tree.configure(yscrollcommand=reg_scroll.set)
        for c in cols:
            self.reg_tree.heading(c, text=c)
            self.reg_tree.column(c, width=120)
        self.reg_tree.pack(side="left", fill="both", expand=True)
        reg_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.reg_tree)
        self.reg_tree.bind("<Double-1>", self.enroll_course)

    def refresh_registration(self):
        for t in self.reg_tree.get_children(): self.reg_tree.delete(t)
        sem_sel = self.reg_sem_var.get()
        if not sem_sel:
            messagebox.showinfo("Info", "Chọn một học kỳ"); return
        sem_id = sem_sel.split(" - ")[0]

        sections = db.list_sections(semester_id=sem_id)
        enrolled = db.get_enrollments(self.mssv, semester_id=sem_id)

        idx = 0
        for s in sections:
            if s['id'] in enrolled:
                continue
            if not s['registration_open']:
                continue
            sched = _get_schedule_display(db, s['id'])
            enrolled_count = db.count_section_enrollments(s['id'])
            remaining = s['max_students'] - enrolled_count
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            self.reg_tree.insert("", "end", values=(
                s['id'], s['subject_id'], s.get('subject_name', ''),
                s.get('lecturer', ''), sched, s['credits_snapshot'],
                s['max_students'], remaining
            ), tags=(tag,))
            idx += 1

    def enroll_course(self, event):
        item = event.widget.selection()
        if not item:
            return
        vals = event.widget.item(item[0])['values']
        section_id = str(vals[0])
        subject_name = vals[2]
        if messagebox.askyesno("Xác nhận", f"Đăng ký lớp {section_id} ({subject_name})?"):
            try:
                services.enroll_student(db, self.mssv, section_id)
                messagebox.showinfo("Success", "Đăng ký thành công!")
                self.refresh_registration()
                self.refresh_schedule()
                self.refresh_payments()
            except Exception as exc:
                messagebox.showerror("Không thể đăng ký", str(exc))

    # ── SCHEDULE ─────────────────────────────────────────────────────────
    def build_schedule(self, parent):
        tk.Label(parent, text="THỜI KHÓA BIỂU", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(15, 5))

        filt = tk.Frame(parent, bg=COLOR_BG)
        filt.pack(fill="x", padx=20, pady=5)
        tk.Label(filt, text="Học kỳ:", bg=COLOR_BG, font=FONT_LABEL).pack(side="left", padx=5)
        self.sched_sem_var = tk.StringVar()
        self.sched_sem_cb = ttk.Combobox(filt, textvariable=self.sched_sem_var, state="readonly", width=35)
        self.sched_sem_cb.pack(side="left", padx=5)
        sems = db.list_semesters()
        self.sched_sem_cb['values'] = ["Tất cả"] + [_sem_cb_value(s) for s in sems]
        _make_btn(filt, "Xem", self.refresh_schedule, width=8).pack(side="left", padx=5)
        _make_btn(filt, "Hủy đăng ký", self.unenroll_course, bg=COLOR_DANGER, width=12).pack(side="left", padx=10)

        cols = ("Mã lớp HP", "Mã môn", "Tên môn", "Giảng viên", "Lịch học", "TC", "HK")
        sched_frame = tk.Frame(parent)
        sched_frame.pack(fill="both", expand=True, padx=20, pady=8)
        self.sched_tree = ttk.Treeview(sched_frame, columns=cols, show="headings")
        sched_scroll = ttk.Scrollbar(sched_frame, orient="vertical", command=self.sched_tree.yview)
        self.sched_tree.configure(yscrollcommand=sched_scroll.set)
        for c in cols: self.sched_tree.heading(c, text=c); self.sched_tree.column(c, width=130)
        self.sched_tree.pack(side="left", fill="both", expand=True)
        sched_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.sched_tree)

        self.refresh_schedule()

    def refresh_schedule(self):
        for t in self.sched_tree.get_children(): self.sched_tree.delete(t)
        sem_sel = self.sched_sem_var.get() if hasattr(self, 'sched_sem_var') else ""
        sem_id = None
        if sem_sel and sem_sel != "Tất cả":
            sem_id = sem_sel.split(" - ")[0]

        enrollments = db.get_enrollment_details(self.mssv, semester_id=sem_id)
        for i, e in enumerate(enrollments):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            sched = _get_schedule_display(db, e['section_id'])
            sem_display = _sem_display(e)
            self.sched_tree.insert("", "end", values=(
                e['section_id'], e['subject_id'], e.get('subject_name', ''),
                e.get('lecturer', ''), sched, e['credits_snapshot'],
                sem_display
            ), tags=(tag,))
        check_empty_treeview(self.sched_tree, "Chưa đăng ký lớp học phần nào")

    def unenroll_course(self):
        item = self.sched_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một lớp HP để hủy"); return
        section_id = str(self.sched_tree.item(item[0])['values'][0])
        if messagebox.askyesno("Xác nhận", f"Hủy đăng ký lớp {section_id}?"):
            try:
                services.unenroll_student(db, self.mssv, section_id, UNENROLL_DEADLINE_DAYS)
                messagebox.showinfo("Success", "Đã hủy đăng ký")
                self.refresh_schedule()
                self.refresh_registration()
                self.refresh_payments()
            except Exception as exc:
                messagebox.showerror("Không thể hủy", str(exc))

    # ── GRADES ───────────────────────────────────────────────────────────
    def build_grades(self, parent):
        tk.Label(parent, text="BẢNG ĐIỂM", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(15, 5))

        filt = tk.Frame(parent, bg=COLOR_BG)
        filt.pack(fill="x", padx=20, pady=5)
        tk.Label(filt, text="Học kỳ:", bg=COLOR_BG, font=FONT_LABEL).pack(side="left", padx=5)
        self.grade_sem_var_st = tk.StringVar()
        self.grade_sem_cb_st = ttk.Combobox(filt, textvariable=self.grade_sem_var_st, state="readonly", width=35)
        self.grade_sem_cb_st.pack(side="left", padx=5)
        sems = db.list_semesters()
        self.grade_sem_cb_st['values'] = ["Tất cả"] + [_sem_cb_value(s) for s in sems]
        _make_btn(filt, "Lọc", self.refresh_grades, width=8).pack(side="left", padx=5)

        cols = ("Mã lớp HP", "Môn", "Học kỳ", "TC", "Giữa kỳ", "Cuối kỳ", "TB")
        grade_frame = tk.Frame(parent)
        grade_frame.pack(fill="both", expand=True, padx=20, pady=8)
        self.grade_tree = ttk.Treeview(grade_frame, columns=cols, show="headings")
        grade_scroll = ttk.Scrollbar(grade_frame, orient="vertical", command=self.grade_tree.yview)
        self.grade_tree.configure(yscrollcommand=grade_scroll.set)
        for c in cols: self.grade_tree.heading(c, text=c); self.grade_tree.column(c, width=130)
        self.grade_tree.pack(side="left", fill="both", expand=True)
        grade_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.grade_tree)

        self.refresh_grades()

    def refresh_grades(self):
        if not hasattr(self, 'grade_tree'):
            return
        for t in self.grade_tree.get_children(): self.grade_tree.delete(t)
        sem_sel = self.grade_sem_var_st.get() if hasattr(self, 'grade_sem_var_st') else ""
        sem_id = None
        if sem_sel and sem_sel != "Tất cả":
            sem_id = sem_sel.split(" - ")[0]
        grades = db.get_grades(self.mssv, semester_id=sem_id)
        for i, g in enumerate(grades):
            mid = g.get('midterm')
            fin = g.get('final_score')
            avg = round((mid + fin) / 2, 1) if mid is not None and fin is not None else "—"
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            sem_display = _sem_display(g)
            self.grade_tree.insert("", "end", values=(
                g['section_id'], g.get('subject_name', ''),
                sem_display, g.get('credits_snapshot', ''),
                mid if mid is not None else "—",
                fin if fin is not None else "—", avg
            ), tags=(tag,))
        check_empty_treeview(self.grade_tree, "Chưa có dữ liệu điểm")

    # ── PROFILE ──────────────────────────────────────────────────────────
    def build_profile(self, parent):
        for w in parent.winfo_children(): w.destroy()

        tk.Label(parent, text="HỒ SƠ CÁ NHÂN", font=FONT_TITLE, bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=20)

        user = db.get_user("Student", self.username)
        students = db.list_students()
        my_info = next((s for s in students if s['username'] == self.username), None)

        lf = tk.LabelFrame(parent, text="Thông tin cá nhân", bg=COLOR_BG,
                           fg=COLOR_PRIMARY, font=FONT_BODY, padx=20, pady=15)
        lf.pack(pady=12, padx=60)

        # Read-only info
        tk.Label(lf, text=f"MSSV: {user['mssv']}", bg=COLOR_BG, font=FONT_LABEL).pack(pady=4)
        if my_info:
            cls = my_info.get('class_name', '—')
            prog = my_info.get('program_name', '—')
            batch = my_info.get('batch_name', '—')
            tk.Label(lf, text=f"Lớp HC: {cls}  |  Ngành: {prog}  |  Khóa: {batch}",
                     bg=COLOR_BG, font=FONT_LABEL, fg="#6B7280").pack(pady=4)

        self.profile_vars = {
            "name": tk.StringVar(value=user.get('name', '') or ''),
            "gender": tk.StringVar(value=user.get('gender', '') or ''),
            "email": tk.StringVar(value=user.get('email', '') or ''),
            "phone": tk.StringVar(value=user.get('phone', '') or ''),
            "address": tk.StringVar(value=user.get('address', '') or ''),
        }

        field_labels = {"name": "Họ tên", "gender": "Giới tính", "email": "Email",
                        "phone": "Điện thoại", "address": "Địa chỉ"}
        self.profile_entries = {}
        for key, text in field_labels.items():
            row = tk.Frame(lf, bg=COLOR_BG)
            row.pack(pady=6)
            tk.Label(row, text=f"{text}:", bg=COLOR_BG, font=FONT_LABEL, width=10, anchor="e").pack(side="left")
            entry = tk.Entry(row, textvariable=self.profile_vars[key], font=FONT_ENTRY, width=30, state="disabled")
            entry.pack(side="left", padx=8)
            self.profile_entries[key] = entry

        btn_frame = tk.Frame(parent, bg=COLOR_BG)
        btn_frame.pack(pady=12)
        self.edit_btn = _make_btn(btn_frame, "CHỈNH SỬA", self.edit_profile, bg=COLOR_WARNING)
        self.edit_btn.pack(side="left", padx=10)
        self.save_btn = _make_btn(btn_frame, "LƯU", self.save_profile, bg=COLOR_SUCCESS)
        self.save_btn.pack(side="left", padx=10)
        self.save_btn.config(state="disabled")

    def edit_profile(self):
        for entry in self.profile_entries.values():
            entry.config(state="normal")
        self.edit_btn.config(state="disabled")
        self.save_btn.config(state="normal")

    def save_profile(self):
        name = self.profile_vars["name"].get().strip()
        gender = self.profile_vars["gender"].get().strip()
        email = self.profile_vars["email"].get().strip()
        phone = self.profile_vars["phone"].get().strip()
        address = self.profile_vars["address"].get().strip()

        if not name or not email:
            messagebox.showerror("Error", "Tên và Email không được để trống"); return
        if "@" not in email or "." not in email:
            messagebox.showerror("Error", "Email không hợp lệ"); return

        try:
            db.update_student_profile(self.username, name=name, gender=gender,
                                      email=email, phone=phone, address=address)
        except Exception as e:
            messagebox.showerror("Error", str(e)); return

        messagebox.showinfo("Success", "Cập nhật thành công!")
        for entry in self.profile_entries.values():
            entry.config(state="disabled")
        self.edit_btn.config(state="normal")
        self.save_btn.config(state="disabled")
        self.root.title(f"Student - {name} ({self.mssv})")

    # ── PAYMENTS ─────────────────────────────────────────────────────────
    def build_payments(self, parent):
        tk.Label(parent, text="HỌC PHÍ", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(15, 5))

        top = tk.Frame(parent, bg=COLOR_BG)
        top.pack(fill="x", padx=20, pady=5)

        tk.Label(top, text="Lớp HP đã đăng ký:", bg=COLOR_BG, font=FONT_LABEL).pack(anchor="w")
        cols = ("Mã lớp HP", "Môn", "TC", "Đơn giá/TC", "Thành tiền", "HK")
        enroll_frame = tk.Frame(top)
        enroll_frame.pack(fill="x", pady=5)
        self.pay_enroll_tree = ttk.Treeview(enroll_frame, columns=cols, show="headings", height=6)
        enroll_scroll = ttk.Scrollbar(enroll_frame, orient="vertical", command=self.pay_enroll_tree.yview)
        self.pay_enroll_tree.configure(yscrollcommand=enroll_scroll.set)
        for c in cols: self.pay_enroll_tree.heading(c, text=c); self.pay_enroll_tree.column(c, width=140)
        self.pay_enroll_tree.pack(side="left", fill="x", expand=True)
        enroll_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.pay_enroll_tree)

        btn_f = tk.Frame(top, bg=COLOR_BG)
        btn_f.pack(anchor="e", pady=5)
        _make_btn(btn_f, "Thanh toán", self.pay_selected, font=FONT_BTN_LG, width=15).pack()

        # Payment history with semester filter
        hist_filter = tk.Frame(parent, bg=COLOR_BG)
        hist_filter.pack(fill="x", padx=20, pady=(10, 0))
        tk.Label(hist_filter, text="Lịch sử giao dịch:", bg=COLOR_BG, font=FONT_LABEL).pack(side="left")
        tk.Label(hist_filter, text="   HK:", bg=COLOR_BG, font=FONT_LABEL).pack(side="left")
        self.pay_sem_var = tk.StringVar()
        self.pay_sem_cb = ttk.Combobox(hist_filter, textvariable=self.pay_sem_var, state="readonly", width=30)
        self.pay_sem_cb.pack(side="left", padx=5)
        sems = db.list_semesters()
        self.pay_sem_cb['values'] = ["Tất cả"] + [_sem_cb_value(s) for s in sems]
        _make_btn(hist_filter, "Lọc", self.refresh_payment_history, width=6).pack(side="left", padx=5)

        cols2 = ("ID", "Lớp HP", "Môn", "Số tiền", "Trạng thái", "Thời gian", "HK")
        hist_frame = tk.Frame(parent)
        hist_frame.pack(fill="both", expand=True, padx=20, pady=5)
        self.pay_hist_tree = ttk.Treeview(hist_frame, columns=cols2, show="headings")
        hist_scroll = ttk.Scrollbar(hist_frame, orient="vertical", command=self.pay_hist_tree.yview)
        self.pay_hist_tree.configure(yscrollcommand=hist_scroll.set)
        for c in cols2: self.pay_hist_tree.heading(c, text=c); self.pay_hist_tree.column(c, width=120)
        self.pay_hist_tree.pack(side="left", fill="both", expand=True)
        hist_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.pay_hist_tree)

        self.refresh_payments()

    def refresh_payments(self):
        if not hasattr(self, 'pay_enroll_tree'):
            return
        for t in self.pay_enroll_tree.get_children(): self.pay_enroll_tree.delete(t)
        enrollments = db.get_enrollment_details(self.mssv)
        for i, e in enumerate(enrollments):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            credits = e['credits_snapshot']
            price = e['tuition_per_credit']
            total = Decimal(str(credits)) * Decimal(str(price))
            sem_display = _sem_display(e)
            self.pay_enroll_tree.insert("", "end", values=(
                e['section_id'], e.get('subject_name', ''), credits,
                f"{float(price):,.0f}", f"{float(total):,.0f}", sem_display
            ), tags=(tag,))
        check_empty_treeview(self.pay_enroll_tree, "Chưa có lớp đăng ký")

        self.refresh_payment_history()

    def refresh_payment_history(self):
        if not hasattr(self, 'pay_hist_tree'):
            return
        for t in self.pay_hist_tree.get_children(): self.pay_hist_tree.delete(t)
        sem_sel = self.pay_sem_var.get() if hasattr(self, 'pay_sem_var') else ""
        sem_id = None
        if sem_sel and sem_sel != "Tất cả":
            sem_id = sem_sel.split(" - ")[0]
        payments = db.list_payments(self.mssv, semester_id=sem_id)
        for i, p in enumerate(payments):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            sem_display = _sem_display(p)
            self.pay_hist_tree.insert("", "end", values=(
                p['id'], p.get('section_id', ''), p.get('subject_name', ''),
                f"{float(p['amount']):,.0f}", p['status'], p.get('time', ''),
                sem_display
            ), tags=(tag,))
        check_empty_treeview(self.pay_hist_tree, "Chưa có giao dịch thanh toán")

    def pay_selected(self):
        item = self.pay_enroll_tree.selection()
        if not item:
            messagebox.showerror("Error", "Chọn một lớp HP để thanh toán"); return
        
        vals = self.pay_enroll_tree.item(item[0])['values']
        # Guard against the "Chưa có lớp đăng ký" empty-message row
        if not vals or len(vals) < 5 or "Chưa có" in str(vals[0]):
            messagebox.showerror("Lỗi", "Vui lòng chọn một lớp học phần hợp lệ."); return

        section_id = str(vals[0])
        subject_name = vals[1]
        total_str = vals[4]
        # Parse total amount
        try:
            total = float(str(total_str).replace(",", ""))
        except ValueError:
            messagebox.showerror("Lỗi", "Không thể đọc số tiền thanh toán."); return

        if not messagebox.askyesno("Xác nhận thanh toán (mô phỏng)",
                                    f"Thanh toán {total_str} VNĐ cho lớp {section_id} ({subject_name})?\n"):
            return
        try:
            pid = services.create_payment(db, self.mssv, section_id, total, status="Paid")
            messagebox.showinfo("Success", f"Ghi nhận thanh toán (ID: {pid})")
            self.refresh_payments()
        except Exception as e:
            messagebox.showerror("Error", str(e))


# ═══════════════════════════════════════════════════════════════════════════
# LECTURER DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

class LecturerDashboard:
    def __init__(self, username):
        self.username = username
        self.root = tk.Tk()
        self.root.protocol("WM_DELETE_WINDOW", lambda: _close_session_window(self.root))
        self.root.title(f"Giảng viên - {username}")
        self.root.geometry("1150x700")
        self.root.minsize(1024, 600)
        self.root.resizable(True, True)
        self.root.configure(bg=COLOR_BG)

        sidebar = tk.Frame(self.root, bg=COLOR_TOPBAR, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="👨‍🏫 Giảng viên", font=("Segoe UI", 10),
                 bg=COLOR_TOPBAR, fg="#B2DFDB").pack(pady=(18, 2))
        tk.Label(sidebar, text=username, font=("Segoe UI", 13, "bold"),
                 bg=COLOR_TOPBAR, fg="white").pack(pady=(0, 18))
        tk.Frame(sidebar, bg="#1A8A8D", height=1).pack(fill="x", padx=15, pady=(0, 10))

        menu_items = [
            "📊  Tổng quan",
            "📚  Lớp HP của tôi",
            "📝  Nhập điểm",
        ]

        self.sidebar_buttons = []
        for i, text in enumerate(menu_items):
            btn = tk.Button(sidebar, text=text, font=("Segoe UI", 11),
                            bg=COLOR_TOPBAR, fg="white", relief="flat",
                            anchor="w", padx=18, pady=10, cursor="hand2",
                            activebackground=COLOR_PRIMARY, activeforeground="white",
                            command=lambda idx=i: self._show_page(idx))
            btn.pack(fill="x")
            self.sidebar_buttons.append(btn)

        tk.Frame(sidebar, bg=COLOR_TOPBAR).pack(fill="both", expand=True)
        tk.Button(sidebar, text="🚪  Đăng xuất", font=FONT_BTN,
                  bg=COLOR_DANGER, fg="white", relief="flat", cursor="hand2", pady=10,
                  activebackground="#C13639", activeforeground="white",
                  command=self.logout).pack(fill="x", padx=12, pady=15)

        content = tk.Frame(self.root, bg=COLOR_BG)
        content.pack(side="right", fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.section_var = tk.StringVar()
        self.loaded_section_id = None
        self.section_var.trace_add("write", self._section_changed)

        self.pages = []
        page_builders = [
            self.build_overview,
            self.build_my_sections,
            self.build_grade_entry,
        ]
        for builder in page_builders:
            page = tk.Frame(content, bg=COLOR_BG)
            page.grid(row=0, column=0, sticky="nsew")
            builder(page)
            self.pages.append(page)

        self._show_page(0)
        self.root.mainloop()

    def _show_page(self, index):
        self.pages[index].tkraise()
        for i, btn in enumerate(self.sidebar_buttons):
            if i == index:
                btn.config(bg=COLOR_PRIMARY, font=("Segoe UI", 11, "bold"))
            else:
                btn.config(bg=COLOR_TOPBAR, font=("Segoe UI", 11))

    def logout(self):
        if messagebox.askyesno("Đăng xuất", "Bạn có chắc muốn đăng xuất?"):
            from .session import session
            session.logout()
            self.root.destroy()
            LoginWindow()

    # ── OVERVIEW ─────────────────────────────────────────────────────────
    def build_overview(self, parent):
        tk.Label(parent, text="TỔNG QUAN GIẢNG VIÊN", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(30, 20))

        cards = tk.Frame(parent, bg=COLOR_BG)
        cards.pack(padx=30, pady=10)
        for c in range(2):
            cards.grid_columnconfigure(c, weight=1)

        sections = db.list_sections(lecturer=self.username)
        num_sections = len(sections)
        num_students = db.count_students_of_lecturer(self.username)

        _make_card(cards, "Số lớp HP đang phụ trách", num_sections, 0)
        _make_card(cards, "Tổng số sinh viên đang dạy", num_students, 1)

    # ── MY SECTIONS ──────────────────────────────────────────────────────
    def build_my_sections(self, parent):
        tk.Label(parent, text="LỚP HỌC PHẦN CỦA TÔI", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(15, 5))

        # Semester filter
        filt = tk.Frame(parent, bg=COLOR_BG)
        filt.pack(fill="x", padx=20, pady=5)
        tk.Label(filt, text="Học kỳ:", bg=COLOR_BG, font=FONT_LABEL).pack(side="left", padx=5)
        self.lect_sem_var = tk.StringVar()
        self.lect_sem_cb = ttk.Combobox(filt, textvariable=self.lect_sem_var, state="readonly", width=35)
        self.lect_sem_cb.pack(side="left", padx=5)
        sems = db.list_semesters()
        self.lect_sem_cb['values'] = ["Tất cả"] + [_sem_cb_value(s) for s in sems]
        _make_btn(filt, "Xem", self.refresh_my_sections, width=8).pack(side="left", padx=5)

        cols = ("Mã lớp HP", "Môn", "Lịch dạy", "TC", "Sĩ số", "Đã ĐK", "HK")
        lect_frame = tk.Frame(parent)
        lect_frame.pack(fill="both", expand=True, padx=20, pady=8)
        self.lect_tree = ttk.Treeview(lect_frame, columns=cols, show="headings")
        lect_scroll = ttk.Scrollbar(lect_frame, orient="vertical", command=self.lect_tree.yview)
        self.lect_tree.configure(yscrollcommand=lect_scroll.set)
        for c in cols: self.lect_tree.heading(c, text=c); self.lect_tree.column(c, width=130)
        self.lect_tree.pack(side="left", fill="both", expand=True)
        lect_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.lect_tree)

        self.refresh_my_sections()

    def refresh_my_sections(self):
        for t in self.lect_tree.get_children(): self.lect_tree.delete(t)
        sem_sel = self.lect_sem_var.get() if hasattr(self, 'lect_sem_var') else ""
        sem_id = None
        if sem_sel and sem_sel != "Tất cả":
            sem_id = sem_sel.split(" - ")[0]

        sections = db.list_sections(lecturer=self.username, semester_id=sem_id)
        for i, s in enumerate(sections):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            sched = _get_schedule_display(db, s['id'])
            enrolled = db.count_section_enrollments(s['id'])
            sem_display = _sem_display(s)
            self.lect_tree.insert("", "end", values=(
                s['id'], s.get('subject_name', ''), sched,
                s['credits_snapshot'], s['max_students'], enrolled,
                sem_display
            ), tags=(tag,))

    # ── GRADE ENTRY ──────────────────────────────────────────────────────
    def build_grade_entry(self, parent):
        tk.Label(parent, text="NHẬP ĐIỂM", font=FONT_TITLE,
                 bg=COLOR_BG, fg=COLOR_PRIMARY).pack(pady=(15, 5))

        filt = tk.Frame(parent, bg=COLOR_BG)
        filt.pack(fill="x", padx=20, pady=5)

        tk.Label(filt, text="HK:", bg=COLOR_BG, font=FONT_LABEL).pack(side="left", padx=5)
        self.grade_sem_var = tk.StringVar()
        self.grade_sem_cb = ttk.Combobox(filt, textvariable=self.grade_sem_var, state="readonly", width=30)
        self.grade_sem_cb.pack(side="left", padx=5)
        sems = db.list_semesters()
        self.grade_sem_cb['values'] = ["Tất cả"] + [_sem_cb_value(s) for s in sems]
        self.grade_sem_cb.bind("<<ComboboxSelected>>", self._update_section_combo)

        tk.Label(filt, text="Lớp HP:", bg=COLOR_BG, font=FONT_LABEL).pack(side="left", padx=5)
        self.section_var = tk.StringVar()
        self.grade_section_cb = ttk.Combobox(filt, textvariable=self.section_var, state="readonly", width=25)
        self.grade_section_cb.pack(side="left", padx=5)

        _make_btn(filt, "Tải DS", self.load_students, width=10).pack(side="left", padx=5)

        cols = ("MSSV", "Họ tên", "Giữa kỳ", "Cuối kỳ")
        grade_frame = tk.Frame(parent)
        grade_frame.pack(fill="both", expand=True, padx=20, pady=8)
        self.grade_tree = ttk.Treeview(grade_frame, columns=cols, show="headings")
        grade_scroll = ttk.Scrollbar(grade_frame, orient="vertical", command=self.grade_tree.yview)
        self.grade_tree.configure(yscrollcommand=grade_scroll.set)
        for c in cols: self.grade_tree.heading(c, text=c); self.grade_tree.column(c, width=200)
        self.grade_tree.pack(side="left", fill="both", expand=True)
        grade_scroll.pack(side="right", fill="y")
        _configure_treeview_tags(self.grade_tree)
        self.grade_tree.bind("<Double-1>", self.enter_grade)

        self._update_section_combo()

    def _update_section_combo(self, event=None):
        sem_sel = self.grade_sem_var.get()
        sem_id = None
        if sem_sel and sem_sel != "Tất cả":
            sem_id = sem_sel.split(" - ")[0]
        sections = db.list_sections(lecturer=self.username, semester_id=sem_id)
        self.grade_section_cb['values'] = [
            f"{s['id']} - {s.get('subject_name', '')}" for s in sections]
        self.loaded_section_id = None
        for item in self.grade_tree.get_children():
            self.grade_tree.delete(item)

    def _section_changed(self, *_):
        self.loaded_section_id = None
        if hasattr(self, 'grade_tree'):
            for item in self.grade_tree.get_children():
                self.grade_tree.delete(item)

    def load_students(self):
        self.loaded_section_id = None
        for item in self.grade_tree.get_children():
            self.grade_tree.delete(item)

        sec_sel = self.section_var.get()
        if not sec_sel:
            messagebox.showinfo("Info", "Chọn một lớp HP"); return
        section_id = sec_sel.split(" - ")[0]

        try:
            section = db.get_section(section_id)
            if not section or section['lecturer'] != self.username:
                raise ValueError("Bạn không được phân công lớp HP này.")
            rows = db.get_section_students_with_grades(section_id)
        except Exception as exc:
            messagebox.showerror("Lỗi", str(exc)); return

        for i, row in enumerate(rows):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.grade_tree.insert("", "end", values=(
                row['mssv'], row.get('student_name', ''),
                row['midterm'] if row['midterm'] is not None else "",
                row['final_score'] if row['final_score'] is not None else ""
            ), tags=(tag,))
        self.loaded_section_id = section_id

    def enter_grade(self, event):
        item = self.grade_tree.selection()
        if not item:
            return
        section_id = self.loaded_section_id
        if not section_id or section_id != (self.section_var.get().split(" - ")[0] if self.section_var.get() else ""):
            messagebox.showerror("Danh sách đã thay đổi",
                                 "Vui lòng tải lại danh sách sinh viên trước khi nhập điểm.")
            return
        mssv = str(self.grade_tree.item(item[0])['values'][0])
        midterm = simpledialog.askfloat("Giữa kỳ", f"Điểm giữa kỳ cho {mssv} / {section_id} (0-10):",
                                         minvalue=0, maxvalue=10)
        if midterm is None:
            return
        final = simpledialog.askfloat("Cuối kỳ", f"Điểm cuối kỳ cho {mssv} / {section_id} (0-10):",
                                       minvalue=0, maxvalue=10)
        if final is None:
            return
        # Recheck after dialog
        current_sel = self.section_var.get().split(" - ")[0] if self.section_var.get() else ""
        if self.loaded_section_id != section_id or current_sel != section_id:
            messagebox.showerror("Danh sách đã thay đổi", "Lớp HP đã thay đổi; vui lòng nhập lại.")
            return
        try:
            services.set_grade(db, mssv, section_id, midterm, final,
                               lecturer_username=self.username)
        except Exception as exc:
            messagebox.showerror("Không thể lưu điểm", str(exc))
            return
        self.load_students()
        messagebox.showinfo("Thành công", "Đã lưu điểm!")


# START APP
if __name__ == "__main__":
    LoginWindow()
