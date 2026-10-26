"""Stay in Path - private, offline Windows habit tracker and desktop widget."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from storage import Store
from ui import (
    AnimatedBar, AnimatedNumber, Aurora, CYAN, DANGER, FAINT, FadeOverlay,
    GlowCard, Heatmap, MINT, MUTED, NavButton, Ring, SidePanel, Sparkline,
    STYLESHEET, Switch, TEXT, TimerRing, Toast, VIOLET, display_font,
)

APP_TITLE = 'Stay in Path'
# A session that was "running" for longer than this at startup is treated as an
# interrupted session and the user is asked whether to keep the elapsed time.
RESUME_GRACE_SECONDS = 15 * 60


def asset_path(name: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / 'assets' / name


def autostart_command():
    if getattr(sys, 'frozen', False):
        return subprocess.list2cmdline([sys.executable, '--minimized'])
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    interpreter = str(pythonw if pythonw.exists() else sys.executable)
    return subprocess.list2cmdline([interpreter, str(Path(__file__).resolve()), '--minimized'])


def is_autostart_enabled():
    if os.name != 'nt':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            return winreg.QueryValueEx(key, 'StayInPath')[0] == autostart_command()
    except OSError:
        return False


def configure_autostart(enabled: bool):
    if os.name != 'nt':
        raise OSError('Autostart is supported only on Windows.')
    import winreg
    registry_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
        if enabled:
            winreg.SetValueEx(key, 'StayInPath', 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, 'StayInPath')
            except FileNotFoundError:
                pass


def label(text: str, size: int = 11, color: str = TEXT, bold: bool = False,
          spacing: float = 0.0, wrap: bool = False):
    w = QLabel(text)
    # Word wrap must stay off for headings and stat captions: inside a horizontal
    # layout a wrapping label collapses to its minimum width and disappears.
    w.setWordWrap(wrap)
    w.setFont(display_font(size, 700 if bold else 400, spacing))
    w.setStyleSheet(f'color:{color}; background:transparent;')
    return w


def button(text: str, primary: bool = False):
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        b.setProperty('primary', True)
    return b


def card_layout(padding=(20, 18, 20, 18), spacing: int = 12, accent: str = MINT):
    card = GlowCard(accent=accent)
    ly = QVBoxLayout(card)
    ly.setContentsMargins(*padding)
    ly.setSpacing(spacing)
    return card, ly


def section_title(title: str, description: str = ''):
    box = QWidget()
    ly = QVBoxLayout(box)
    ly.setContentsMargins(0, 2, 0, 6)
    ly.setSpacing(6)
    row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(12)
    bar = QWidget(); bar.setFixedSize(4, 27)
    bar.setStyleSheet(f'background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {MINT}, stop:1 {CYAN});'
                      'border-radius:2px;')
    rl.addWidget(bar)
    rl.addWidget(label(title, 27, '#ffffff', True, 0.6))
    rl.addStretch()
    ly.addWidget(row)
    if description:
        ly.addWidget(label(description, 11, MUTED, spacing=0.2, wrap=True))
    return box


def stat_card(caption: str, value_widget: QWidget, accent: str, spark: QWidget | None = None):
    card, ly = card_layout(padding=(18, 15, 18, 15), spacing=9)
    head = QWidget(); hl = QHBoxLayout(head); hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(7)
    dot = QWidget(); dot.setFixedSize(6, 6)
    dot.setStyleSheet(f'background:{accent}; border-radius:3px;')
    hl.addWidget(dot)
    hl.addWidget(label(caption, 9, MUTED, True, 1.5))
    hl.addStretch()
    ly.addWidget(head)
    ly.addWidget(value_widget)
    if spark is not None:
        ly.addWidget(spark)
    return card


def format_duration(seconds: float) -> str:
    secs = int(max(0, seconds))
    hours, rem = divmod(secs, 3600)
    minutes, secs = divmod(rem, 60)
    return f'{hours}h {minutes}m' if hours else f'{minutes}m {secs}s'


def deadline_text(deadline: str) -> str:
    if not deadline:
        return ''
    try:
        target = date.fromisoformat(deadline)
    except ValueError:
        return f'Deadline {deadline}'
    left = (target - date.today()).days
    if left < 0:
        return f'Deadline {deadline}  ·  overdue'
    if left == 0:
        return f'Deadline {deadline}  ·  due today'
    return f'Deadline {deadline}  ·  {left} days left'


class FadeStack(QStackedWidget):
    """Stack that crossfades to a fresh page using a snapshot of the old one."""

    def replace_current(self, widget: QWidget, fade: bool = True):
        old = self.currentWidget()
        self.addWidget(widget)
        self.setCurrentWidget(widget)
        if old is None:
            return
        if not fade or not old.isVisible():
            self.removeWidget(old)
            old.deleteLater()
            return
        overlay = FadeOverlay(old.grab(), self)
        overlay.setGeometry(old.geometry())
        overlay.start()
        self.removeWidget(old)
        old.deleteLater()


class DesktopWidget(QWidget):
    """Movable always-on-top mini gadget (not a Windows Explorer embedded gadget)."""
    def __init__(self, app_window):
        super().__init__()
        self.owner = app_window
        self.setWindowTitle('Stay in Path Widget')
        self.setWindowIcon(app_window.app_icon)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(372)
        self.drag_pos = None
        self._refresh_pending = False
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(4, 4, 4, 4)
        self.refresh()
        pos = app_window.store.setting('widget_position')
        if pos and ',' in pos:
            try:
                x, y = map(int, pos.split(','))
                self.move(x, y)
            except (TypeError, ValueError):
                pass
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.right() - self.width() - 18, screen.top() + 45)

    def schedule_refresh(self):
        """Defer the rebuild so a switch is never destroyed inside its own signal."""
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._flush_refresh)

    def _flush_refresh(self):
        self._refresh_pending = False
        self.refresh()

    def refresh(self):
        while self.root.count():
            item = self.root.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        panel, ly = card_layout(padding=(17, 15, 17, 15), spacing=10)
        header = QWidget(); row = QHBoxLayout(header); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label('◈  STAY IN PATH', 12, MINT, True, 1.2)); row.addStretch()
        open_b = button('↗'); open_b.setFixedWidth(32); open_b.setToolTip('Open dashboard')
        open_b.clicked.connect(lambda: self.owner.show_page('Dashboard'))
        hide_b = button('×'); hide_b.setFixedWidth(32); hide_b.setToolTip('Hide widget')
        hide_b.clicked.connect(self.owner.hide_widget)
        row.addWidget(open_b); row.addWidget(hide_b); ly.addWidget(header)
        mission = self.owner.store.get_mission()
        ly.addWidget(label('MAIN MISSION', 8, FAINT, True, 1.6))
        ly.addWidget(label(mission['title'], 12, '#ffffff', True))
        ly.addWidget(AnimatedBar(mission['completed'] / max(1, mission['total']), 6))
        s, longest = self.owner.store.streaks()
        ly.addWidget(label(f'🔥  {s} day streak     •     Best {longest} days', 11, '#d9f5e7', True))
        ly.addWidget(Heatmap(self.owner.store.calendar(91), compact=True))
        habits = self.owner.store.habits()
        if not habits:
            ly.addWidget(label('Add your first habit from the dashboard.', 11, MUTED, wrap=True))
        for h in habits[:4]:
            value = self.owner.store.log_value(h['id'])
            rr = QWidget(); hly = QHBoxLayout(rr); hly.setContentsMargins(0, 0, 0, 0); hly.setSpacing(10)
            hly.addWidget(label(h['name'][:26], 11))
            hly.addStretch()
            if h['kind'] == 'yesno':
                switch = Switch(); switch.setChecked(value >= 1)
                switch.toggled.connect(lambda checked, hid=h['id']: self.owner.update_log(hid, 1 if checked else 0))
                hly.addWidget(switch)
            else:
                hly.addWidget(label(f'{int(value)}/{h["goal_minutes"]} min', 10, MINT))
            ly.addWidget(rr)
        if len(habits) > 4:
            ly.addWidget(label(f'+ {len(habits)-4} more habits in app', 10, MUTED))
        focus = button('▶  Open focus timer', True)
        focus.clicked.connect(lambda: self.owner.show_page('Focus Timer'))
        ly.addWidget(focus)
        self.root.addWidget(panel)
        self.adjustSize()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 52:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drag_pos is not None:
            self.owner.store.save_setting('widget_position', f'{self.x()},{self.y()}')
        self.drag_pos = None
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    NAV = ('Dashboard', 'Habits', 'Main Mission', 'Focus Timer', 'Weekly Review')

    def __init__(self):
        super().__init__()
        self.store = Store()
        self.app_icon = QIcon(str(asset_path('stay-in-path.png')))
        self.setWindowIcon(self.app_icon)
        self.setWindowTitle('Stay in Path — Consistency makes progress')
        self.resize(1120, 800)
        self.setMinimumSize(900, 640)
        self.focus_id = None
        self.running_seconds = 0.0
        self.started_wall = None          # wall-clock start of the current running segment
        self.paused = False
        self.page_name = 'Dashboard'
        self.page_refreshers = []         # cheap in-place updates for the current page
        self.timer_ring = None
        self.focus_picker = None
        self.widget = None
        self.really_quit = False
        self._store_closed = False
        self._fade_pages = False
        self.setup_ui()
        self.setup_tray()
        self.toast = Toast(self)
        self.widget = DesktopWidget(self)
        if self.store.setting('widget_visible', '1') != '0':
            self.widget.show()
        self.update_widget_action()
        self.show_page('Dashboard', reveal=False)
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.update_clock)
        self.clock.start(1000)
        self.refresh_clock = QTimer(self)
        self.refresh_clock.timeout.connect(lambda: self.refresh_views(fade=False))
        self.refresh_clock.start(60000)
        QTimer.singleShot(0, self.restore_focus)

    def setup_ui(self):
        QApplication.instance().setStyleSheet(STYLESHEET)
        central = Aurora(); self.setCentralWidget(central)
        lay = QHBoxLayout(central); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        sidebar = SidePanel(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(232)
        side = QVBoxLayout(sidebar); side.setContentsMargins(18, 24, 18, 20); side.setSpacing(10)
        brand = QWidget(); header = QHBoxLayout(brand); header.setContentsMargins(2, 0, 0, 18); header.setSpacing(11)
        brand_icon = QLabel(); brand_icon.setPixmap(self.app_icon.pixmap(QSize(40, 40)))
        header.addWidget(brand_icon)
        header.addWidget(label('STAY IN\nPATH', 13, MINT, True, 2.0)); header.addStretch()
        side.addWidget(brand)
        self.nav_buttons = {}
        symbols = {'Dashboard': '▦', 'Habits': '✓', 'Main Mission': '◎', 'Focus Timer': '◷', 'Weekly Review': '▥'}
        for name in self.NAV:
            nav = NavButton(symbols[name], name)
            nav.clicked.connect(lambda _=False, n=name: self.show_page(n))
            side.addWidget(nav)
            self.nav_buttons[name] = nav
        side.addStretch()
        status_card, status_layout = card_layout(padding=(14, 12, 14, 12), spacing=5, accent=CYAN)
        status_layout.addWidget(label('FOCUS', 8, FAINT, True, 1.8))
        self.side_focus = label('idle', 13, MINT, True, 0.4)
        status_layout.addWidget(self.side_focus)
        self.side_hint = label('All data stays on this PC.', 9, MUTED, wrap=True)
        status_layout.addWidget(self.side_hint)
        side.addWidget(status_card)
        lay.addWidget(sidebar)
        self.pages = FadeStack()
        lay.addWidget(self.pages, 1)

    def setup_tray(self):
        self.tray = QSystemTrayIcon(self.app_icon, self)
        menu = QMenu()
        menu.addAction('Open Stay in Path', lambda: self.show_page('Dashboard'))
        self.widget_action = menu.addAction('Show desktop widget', self.toggle_widget)
        menu.addSeparator()
        menu.addAction('Quit completely', self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip('Stay in Path — offline habit tracker')
        self.tray.activated.connect(lambda reason: self.show_page('Dashboard') if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def update_widget_action(self):
        if self.widget is not None:
            self.widget_action.setText('Hide desktop widget' if self.widget.isVisible() else 'Show desktop widget')

    def show_widget(self):
        if self.widget is None:
            return
        self.widget.refresh()
        self.widget.show()
        self.widget.raise_()
        self.store.save_setting('widget_visible', '1')
        self.update_widget_action()
        self.refresh_live()

    def hide_widget(self):
        if self.widget is None:
            return
        self.widget.hide()
        self.store.save_setting('widget_visible', '0')
        self.update_widget_action()
        self.refresh_live()

    def set_widget_visible(self, shown: bool):
        """Set the state explicitly instead of toggling, so the checkbox can never desync."""
        if self.widget is None:
            return
        if shown:
            self.show_widget()
        else:
            self.hide_widget()

    def toggle_widget(self):
        if self.widget is None:
            return
        self.set_widget_visible(not self.widget.isVisible())

    def set_autostart(self, enabled: bool):
        try:
            configure_autostart(enabled)
        except OSError as exc:
            QMessageBox.warning(self, 'Startup setting failed', str(exc))
        self.refresh_page()

    def notify(self, title: str, body: str, accent: str = MINT):
        try:
            self.toast.show_message(title, body, accent)
        except Exception:
            pass

    def quit_app(self):
        if self.session_active():
            answer = QMessageBox.question(
                self, 'Focus session running',
                'A focus session is still running or paused.\n\nQuit anyway? '
                'The session is saved and will be offered again next time you open Stay in Path.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.persist_focus()
        self.really_quit = True
        self.tray.hide()
        if self.widget is not None:
            self.widget.close()
        self.close_store()
        # quit() can silently fail to end the loop in this PySide6 build when a
        # frameless tool window and the animated background are alive; exit() is reliable.
        QApplication.instance().exit(0)

    def close_store(self):
        if not self._store_closed:
            self._store_closed = True
            if getattr(self, 'clock', None) is not None:
                self.clock.stop()
            if getattr(self, 'refresh_clock', None) is not None:
                self.refresh_clock.stop()
            self.store.close()

    def closeEvent(self, event):
        if self.really_quit:
            event.accept()
            return
        if QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            self.notify('Still running', 'Stay in Path lives in the tray. Use Quit to exit.', CYAN)
            return
        # No tray: closing really exits. Cancel on the prompt must leave the window usable.
        if self.session_active():
            event.ignore()
            self.quit_app()
            return
        self.really_quit = True
        if self.widget is not None:
            self.widget.close()
        self.close_store()
        event.accept()
        QTimer.singleShot(0, lambda: QApplication.instance().exit(0))

    # ---------------------------------------------------------------- focus timer

    def session_active(self) -> bool:
        return self.started_wall is not None or self.paused

    def elapsed_seconds(self) -> float:
        """Wall-clock based, so laptop sleep and clock drift no longer lose time."""
        if self.started_wall is None:
            return max(0.0, self.running_seconds)
        return max(0.0, self.running_seconds + (datetime.now() - self.started_wall).total_seconds())

    def persist_focus(self):
        if not self.session_active() or self.focus_id is None:
            self.store.clear_focus_state()
            return
        segment = self.started_wall.isoformat(timespec='seconds') if self.started_wall else ''
        self.store.save_focus_state(self.focus_id, self.running_seconds, self.paused, segment)

    def clear_focus(self):
        self.running_seconds = 0.0
        self.started_wall = None
        self.paused = False
        self.store.clear_focus_state()

    def restore_focus(self):
        state = self.store.focus_state()
        if not state:
            return
        habit_id = state.get('habit_id')
        habits = {h['id']: h for h in self.store.habits()}
        if habit_id not in habits:
            # The habit was archived or deleted while the session was pending.
            self.store.clear_focus_state()
            return
        self.focus_id = habit_id
        self.running_seconds = max(0.0, float(state.get('running_seconds') or 0))
        segment = state.get('segment_start') or ''
        name = habits[habit_id]['name']
        if state.get('paused') or not segment:
            self.paused = True
            self.started_wall = None
            self.persist_focus()
            if self.page_name == 'Focus Timer':
                self.refresh_page()
            return
        try:
            started = datetime.fromisoformat(segment)
        except ValueError:
            started = None
        gap = max(0.0, (datetime.now() - started).total_seconds()) if started else 0.0
        if gap > RESUME_GRACE_SECONDS:
            keep = True
            if self.isVisible():
                answer = QMessageBox.question(
                    self, 'Unfinished focus session',
                    f'A session for “{name}” was still running when Stay in Path last closed '
                    f'(about {format_duration(self.running_seconds + gap)} of tracked time).\n\n'
                    'Keep that time and continue the session?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes)
                keep = answer == QMessageBox.StandardButton.Yes
            if not keep:
                self.clear_focus()
            else:
                # Keep the elapsed time but stop the clock: ticking through a night
                # (or an autostart launch) would be a silent lie.
                self.running_seconds += gap
                self.paused = True
                self.started_wall = None
        else:
            # Short gap (quick restart or sleep): quietly continue the same session.
            self.running_seconds += gap
            self.started_wall = datetime.now()
            self.paused = False
        self.persist_focus()
        if self.page_name == 'Focus Timer':
            self.refresh_page()

    # ---------------------------------------------------------------- shell

    def show_page(self, name: str, reveal: bool = True):
        self.page_name = name
        self.refresh_page(fade=True)
        for n, b in self.nav_buttons.items():
            b.set_active(n == name)
        if reveal:
            self.showNormal(); self.raise_(); self.activateWindow()

    def refresh_page(self, fade: bool = False):
        self.timer_ring = None
        self.focus_picker = None
        self.page_refreshers = []
        builders = {
            'Dashboard': self.dashboard, 'Habits': self.habits_page,
            'Main Mission': self.mission_page, 'Focus Timer': self.focus_page,
            'Weekly Review': self.weekly_page,
        }
        new_page = self.scroller(builders[self.page_name]())
        self.pages.replace_current(new_page, fade=fade)
        self.update_clock()

    @staticmethod
    def scroller(content: QWidget):
        area = QScrollArea(); area.setWidgetResizable(True); area.setWidget(content)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return area

    def refresh_views(self, fade: bool = True):
        if self._store_closed:
            return
        self.refresh_page(fade=fade)
        if self.widget is not None:
            self.widget.schedule_refresh()

    def refresh_live(self):
        """Update only the widgets that depend on today's logs (no page rebuild)."""
        for refresher in list(self.page_refreshers):
            try:
                refresher()
            except RuntimeError:
                # The page was replaced while the refresher was queued.
                pass

    def page_layout(self):
        root = QWidget(); root.setObjectName('page')
        ly = QVBoxLayout(root); ly.setContentsMargins(30, 26, 30, 26); ly.setSpacing(18)
        return root, ly

    # ---------------------------------------------------------------- dashboard

    def dashboard(self):
        root, ly = self.page_layout()
        header = QWidget(); hl = QHBoxLayout(header); hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(section_title('Dashboard', 'Show up consistently. Make meaningful progress.'), 1)
        today_tag = label(date.today().strftime('%A · %d %B %Y').upper(), 9, FAINT, True, 1.8)
        hl.addWidget(today_tag, 0, Qt.AlignmentFlag.AlignTop)
        ly.addWidget(header)

        mission = self.store.get_mission()
        mission_progress = mission['completed'] / max(1, mission['total'])
        mc, ml = card_layout(padding=(22, 20, 22, 20))
        body = QWidget(); bl = QHBoxLayout(body); bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(24)
        ring = Ring(mission_progress, 128, 9, 'mission')
        ring.set_center_text(f'{round(mission_progress * 100)}%')
        bl.addWidget(ring)
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(8)
        rl.addWidget(label('◎  MAIN MISSION', 9, MINT, True, 1.8))
        rl.addWidget(label(mission['title'], 21, '#ffffff', True, 0.4))
        rl.addWidget(label(f'{mission["completed"]} of {mission["total"]} milestones complete', 11, MUTED))
        deadline = deadline_text(mission['deadline'])
        if deadline:
            rl.addWidget(label(deadline, 10, FAINT))
        rl.addSpacing(4)
        rl.addWidget(AnimatedBar(mission_progress, 8))
        rl.addSpacing(6)
        modify = button('Edit mission'); modify.clicked.connect(lambda: self.show_page('Main Mission'))
        row = QWidget(); rowl = QHBoxLayout(row); rowl.setContentsMargins(0, 0, 0, 0)
        rowl.addWidget(modify); rowl.addStretch()
        rl.addWidget(row)
        rl.addStretch()
        bl.addWidget(right, 1)
        ml.addWidget(body)
        ly.addWidget(mc)

        current, longest = self.store.streaks()
        fourteen = list(self.store.calendar(14).values())
        today_values = self.store.calendar(1)
        rate = next(iter(today_values.values()))
        streak_num = AnimatedNumber(current, ' days', size=27)
        longest_num = AnimatedNumber(longest, ' days', size=27, color=CYAN)
        today_num = AnimatedNumber(round(rate * 100) if rate is not None else 0, '%', size=27, color=VIOLET)
        if rate is None:
            today_num.setText('—')
        spark = Sparkline(fourteen, 30)
        grid = QGridLayout(); grid.setSpacing(14)
        grid.addWidget(stat_card('CURRENT STREAK', streak_num, MINT, Sparkline(fourteen, 30)), 0, 0)
        grid.addWidget(stat_card('LONGEST STREAK', longest_num, CYAN, Sparkline(fourteen, 30)), 0, 1)
        grid.addWidget(stat_card('TODAY', today_num, VIOLET, spark), 0, 2)
        ly.addLayout(grid)

        hc, hl2 = card_layout()
        heading = QWidget(); hlr = QHBoxLayout(heading); hlr.setContentsMargins(0, 0, 0, 0)
        hlr.addWidget(label('CONSISTENCY  ·  LAST 13 WEEKS', 10, MUTED, True, 1.6))
        hlr.addStretch()
        hlr.addWidget(label('◷  live', 9, FAINT, True, 1.2))
        hl2.addWidget(heading)
        heat = Heatmap(self.store.calendar(91))
        hl2.addWidget(heat)
        ly.addWidget(hc)

        def sync_stats():
            cur, best = self.store.streaks()
            streak_num.set_value(cur)
            longest_num.set_value(best)
            values = list(self.store.calendar(14).values())
            today_rate = values[-1]
            if today_rate is None:
                today_num.setText('—')
            else:
                today_num.set_value(round(today_rate * 100))
            spark.set_values(values)
            heat.set_data(self.store.calendar(91))
        self.page_refreshers.append(sync_stats)

        habits = self.store.habits()
        cc, cl = card_layout()
        title_row = QWidget(); hr = QHBoxLayout(title_row); hr.setContentsMargins(0, 0, 0, 0)
        hr.addWidget(label('TODAY’S HABITS', 10, MUTED, True, 1.6)); hr.addStretch()
        add = button('+ Add habit', True); add.clicked.connect(self.add_habit_dialog); hr.addWidget(add)
        cl.addWidget(title_row)
        if not habits:
            cl.addWidget(label('No habits yet. Create a Yes/No or timed habit to begin.', 11, MUTED, wrap=True))
        for h in habits:
            cl.addWidget(self.habit_row(h))
        ly.addWidget(cc)

        settings, sl = card_layout(accent=CYAN)
        sl.addWidget(label('DESKTOP & STARTUP', 10, MUTED, True, 1.6))
        wcheck = QCheckBox('Show floating desktop widget')
        wcheck.setChecked(self.widget.isVisible() if self.widget is not None else True)
        wcheck.toggled.connect(self.set_widget_visible)
        sl.addWidget(wcheck)
        acheck = QCheckBox('Start with Windows')
        acheck.setEnabled(os.name == 'nt')
        acheck.setChecked(is_autostart_enabled())
        acheck.toggled.connect(self.set_autostart)
        sl.addWidget(acheck)

        def sync_settings():
            if self.widget is not None:
                wcheck.blockSignals(True)
                wcheck.setChecked(self.widget.isVisible())
                wcheck.blockSignals(False)
        self.page_refreshers.append(sync_settings)
        ly.addWidget(settings)
        ly.addStretch()
        return root

    def habit_row(self, h, show_name: bool = True):
        container = QWidget()
        col = QVBoxLayout(container); col.setContentsMargins(0, 6, 0, 6); col.setSpacing(7)
        row = QWidget(); line = QHBoxLayout(row); line.setContentsMargins(0, 0, 0, 0); line.setSpacing(14)
        if show_name:
            line.addWidget(label(h['name'], 13, '#f2fff8', True), 1)
        else:
            line.addStretch(1)
        value = self.store.log_value(h['id'])
        if h['kind'] == 'yesno':
            switch = Switch(); switch.setChecked(value >= 1)
            switch.toggled.connect(lambda checked, hid=h['id']: self.update_log(hid, 1 if checked else 0))
            line.addWidget(switch)
        else:
            line.addWidget(label(f'/ {h["goal_minutes"]} min', 10, MUTED))
            spin = QSpinBox(); spin.setRange(0, 9999); spin.setSuffix(' min'); spin.setValue(round(value)); spin.setFixedWidth(118)
            spin.setToolTip('Manual total minutes today. Focus sessions also add time.')
            spin.editingFinished.connect(lambda hid=h['id'], control=spin: self.update_log(hid, control.value()))
            line.addWidget(spin)
        col.addWidget(row)
        if h['kind'] == 'time':
            bar = AnimatedBar(min(1.0, value / max(1, h['goal_minutes'])), 6)
            col.addWidget(bar)

            def sync_bar(hid=h['id'], goal=h['goal_minutes'], bar=bar):
                bar.set_value(min(1.0, self.store.log_value(hid) / max(1, goal)))
            self.page_refreshers.append(sync_bar)
        return container

    def update_log(self, habit_id: int, value: float):
        self.store.set_log(habit_id, value)
        # Update the affected numbers in place. Rebuilding the page here used to delete
        # the very switch that emitted the signal.
        self.refresh_live()
        if self.widget is not None:
            self.widget.schedule_refresh()

    # ---------------------------------------------------------------- habits

    def habits_page(self):
        root, ly = self.page_layout()
        ly.addWidget(section_title('Habits', 'Each habit has its own contribution graph and streak.'))
        add = button('+ New habit', True); add.clicked.connect(self.add_habit_dialog)
        add_row = QWidget(); ar = QHBoxLayout(add_row); ar.setContentsMargins(0, 0, 0, 0)
        ar.addWidget(add); ar.addStretch()
        ly.addWidget(add_row)
        habits = self.store.habits()
        if not habits:
            empty, el = card_layout()
            el.addWidget(label('No habits yet.', 14, '#ffffff', True))
            el.addWidget(label('Add your first habit to see the individual contribution graph.', 11, MUTED, wrap=True))
            ly.addWidget(empty)
        for h in habits:
            cc, cl = card_layout()
            heading = QWidget(); hr = QHBoxLayout(heading); hr.setContentsMargins(0, 0, 0, 0); hr.setSpacing(10)
            hr.addWidget(label(h['name'], 17, '#ffffff', True, 0.3)); hr.addStretch()
            edit = button('Edit'); edit.setToolTip('Rename this habit or change its daily target')
            edit.clicked.connect(lambda _=False, habit=h: self.edit_habit_dialog(habit))
            hr.addWidget(edit)
            rm = button('Archive'); rm.setToolTip('Hide the habit without deleting its history')
            rm.clicked.connect(lambda _=False, hid=h['id'], n=h['name']: self.archive_habit(hid, n))
            hr.addWidget(rm); cl.addWidget(heading)
            current, best = self.store.streaks(h['id'])
            kind_text = 'Yes/No habit' if h['kind'] == 'yesno' else f'Timed habit · {h["goal_minutes"]} min/day'
            streak_line = label(f'{kind_text}   •   Current streak: {current} days   •   Best: {best} days', 10, MUTED)
            cl.addWidget(streak_line)
            heat = Heatmap(self.store.calendar(91, h['id']))
            cl.addWidget(heat)
            cl.addWidget(self.habit_row(h, show_name=False))
            ly.addWidget(cc)

            def sync_card(habit_id=h['id'], heat=heat, line=streak_line, kind_text=kind_text):
                cur, best_now = self.store.streaks(habit_id)
                line.setText(f'{kind_text}   •   Current streak: {cur} days   •   Best: {best_now} days')
                heat.set_data(self.store.calendar(91, habit_id))
            self.page_refreshers.append(sync_card)
        ly.addWidget(self.archived_card())
        ly.addStretch(); return root

    def archived_card(self):
        archived = self.store.archived_habits()
        cc, cl = card_layout(accent=CYAN)
        header = QWidget(); hr = QHBoxLayout(header); hr.setContentsMargins(0, 0, 0, 0)
        hr.addWidget(label('ARCHIVED HABITS', 10, MUTED, True, 1.6)); hr.addStretch()
        hr.addWidget(label(str(len(archived)), 10, FAINT, True))
        cl.addWidget(header)
        if not archived:
            cl.addWidget(label('Nothing archived. Archiving hides a habit but keeps its history.', 11, MUTED, wrap=True))
            return cc
        toggle = button('▸  Show archived habits')
        toggle_row = QWidget(); tr = QHBoxLayout(toggle_row); tr.setContentsMargins(0, 0, 0, 0)
        tr.addWidget(toggle); tr.addStretch()
        cl.addWidget(toggle_row)
        container = QWidget(); inner = QVBoxLayout(container)
        inner.setContentsMargins(0, 0, 0, 0); inner.setSpacing(10)

        def set_open(opened: bool):
            container.setVisible(opened)
            toggle.setText('▾  Hide archived habits' if opened else '▸  Show archived habits')

        toggle.clicked.connect(lambda: set_open(not container.isVisible()))
        for h in archived:
            row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(10)
            desc = 'Yes/No' if h['kind'] == 'yesno' else f'{h["goal_minutes"]} min/day'
            rl.addWidget(label(f'{h["name"]}  ·  {desc}', 11, '#dbe8e4'))
            rl.addStretch()
            restore = button('Restore')
            restore.setToolTip('Bring this habit back into your active lists')
            restore.clicked.connect(lambda _=False, hid=h['id']: self.restore_habit(hid))
            rl.addWidget(restore)
            destroy = button('Delete permanently')
            destroy.setToolTip('Erase this habit together with all of its history')
            destroy.clicked.connect(lambda _=False, hid=h['id'], n=h['name']: self.delete_habit_permanently(hid, n))
            rl.addWidget(destroy)
            inner.addWidget(row)
        cl.addWidget(container)
        set_open(False)
        return cc

    def habit_form_dialog(self, title: str, habit=None):
        """Shared create/edit form. Returns (name, kind, goal) or None."""
        dlg = QDialog(self); dlg.setWindowTitle(title); dlg.setMinimumWidth(400)
        form = QFormLayout(dlg); form.setSpacing(13)
        name = QLineEdit(habit['name'] if habit else '')
        name.setPlaceholderText('e.g. Build my app'); name.setMaxLength(80)
        kind = QComboBox(); kind.addItems(['Yes / No', 'Time (minutes)'])
        goal = QSpinBox(); goal.setRange(1, 1440); goal.setSuffix(' min/day')
        if habit:
            kind.setCurrentIndex(1 if habit['kind'] == 'time' else 0)
            kind.setEnabled(False)
            kind.setToolTip('The habit type cannot be changed after creation.')
            goal.setValue(max(1, int(habit['goal_minutes'])))
        else:
            goal.setValue(60)
        goal.setEnabled(kind.isEnabled() and kind.currentIndex() == 1)
        kind.currentIndexChanged.connect(lambda i: goal.setEnabled(kind.isEnabled() and i == 1))
        form.addRow('Habit name:', name); form.addRow('Type:', kind); form.addRow('Daily target:', goal)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(dlg.accept); controls.rejected.connect(dlg.reject)
        form.addRow(controls)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return name.text(), ('time' if kind.currentIndex() == 1 else 'yesno'), goal.value()

    def add_habit_dialog(self):
        result = self.habit_form_dialog('Create habit')
        if result is None:
            return
        name, kind, goal = result
        try:
            self.store.add_habit(name, kind, goal)
        except ValueError as err:
            QMessageBox.warning(self, 'Invalid habit', str(err))
            return
        self.refresh_views()

    def edit_habit_dialog(self, habit):
        result = self.habit_form_dialog(f'Edit “{habit["name"]}”', habit)
        if result is None:
            return
        name, _kind, goal = result
        try:
            self.store.update_habit(habit['id'], name, goal if habit['kind'] == 'time' else 1)
        except ValueError as err:
            QMessageBox.warning(self, 'Invalid habit', str(err))
            return
        self.refresh_views()

    def archive_habit(self, habit_id: int, name: str):
        if habit_id == self.focus_id and self.session_active():
            QMessageBox.information(self, 'Timer active', 'Stop and save your current focus session first.')
            return
        if QMessageBox.question(self, 'Archive habit',
                                f'Archive “{name}”? Existing history remains saved.') == QMessageBox.StandardButton.Yes:
            self.store.delete_habit(habit_id)
            if self.focus_id == habit_id:
                self.focus_id = None
                self.clear_focus()
            self.notify('Habit archived', f'“{name}” moved to Archived habits.', CYAN)
            self.refresh_views()

    def restore_habit(self, habit_id: int):
        self.store.restore_habit(habit_id)
        self.notify('Habit restored', 'It is back in your active lists.')
        self.refresh_views()

    def delete_habit_permanently(self, habit_id: int, name: str):
        if habit_id == self.focus_id and self.session_active():
            QMessageBox.information(self, 'Timer active', 'Stop and save your current focus session first.')
            return
        answer = QMessageBox.warning(
            self, 'Delete habit permanently',
            f'Delete “{name}” and every logged day for it?\n\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_habit_permanently(habit_id)
        if self.focus_id == habit_id:
            self.focus_id = None
            self.clear_focus()
        self.notify('Habit deleted', f'“{name}” and its history were erased.', DANGER)
        self.refresh_views()

    # ---------------------------------------------------------------- mission

    def mission_page(self):
        root, ly = self.page_layout()
        ly.addWidget(section_title('Main Mission', 'Keep one meaningful goal in front of you.'))
        m = self.store.get_mission()
        cc, cl = card_layout()
        top = QWidget(); tl = QHBoxLayout(top); tl.setContentsMargins(0, 0, 0, 0); tl.setSpacing(24)
        progress = m['completed'] / max(1, m['total'])
        ring = Ring(progress, 118, 8, 'saved')
        ring.set_center_text(f'{round(progress * 100)}%')
        tl.addWidget(ring)
        meta = QWidget(); ml = QVBoxLayout(meta); ml.setContentsMargins(0, 0, 0, 0); ml.setSpacing(6)
        ml.addWidget(label('CURRENT MISSION', 9, MINT, True, 1.8))
        ml.addWidget(label(m['title'], 18, '#ffffff', True, 0.3))
        ml.addWidget(label(f'{m["completed"]} / {m["total"]} milestones', 11, MUTED))
        if m['deadline']:
            ml.addWidget(label(deadline_text(m['deadline']), 10, FAINT))
        ml.addStretch()
        tl.addWidget(meta, 1)
        cl.addWidget(top)
        cl.addWidget(label('MISSION TITLE', 9, MUTED, True, 1.6))
        title = QLineEdit(m['title']); title.setMaxLength(140); cl.addWidget(title)
        cl.addWidget(label('MILESTONES / STEPS', 9, MUTED, True, 1.6))
        hr = QHBoxLayout(); done = QSpinBox(); done.setRange(0, 9999); done.setValue(m['completed'])
        total = QSpinBox(); total.setRange(1, 9999); total.setValue(m['total'])
        hr.addWidget(label('Completed')); hr.addWidget(done)
        hr.addWidget(label('Total')); hr.addWidget(total); hr.addStretch()
        cl.addLayout(hr)

        def preview():
            ratio = done.value() / max(1, total.value())
            ring.set_progress(ratio)
            ring.set_center_text(f'{round(ratio * 100)}%')
        done.valueChanged.connect(preview); total.valueChanged.connect(preview)
        cl.addWidget(label('OPTIONAL DEADLINE (YYYY-MM-DD)', 9, MUTED, True, 1.6))
        deadline = QLineEdit(m['deadline']); deadline.setPlaceholderText('e.g. 2026-12-15'); cl.addWidget(deadline)
        save = button('Save mission', True)

        def save_mission():
            try:
                self.store.save_mission(title.text(), done.value(), total.value(), deadline.text().strip())
            except (ValueError, OverflowError) as err:
                QMessageBox.warning(self, 'Invalid mission', str(err)); return
            self.notify('Mission updated', 'Milestones saved. Keep moving.', MINT)
            self.refresh_views()
        save.clicked.connect(save_mission); cl.addWidget(save)
        ly.addWidget(cc)
        info, il = card_layout(accent=CYAN); il.addWidget(label('PROGRESS ≠ TIME SPENT', 10, CYAN, True, 1.6))
        il.addWidget(label('Mark a milestone completed only when you finish a real deliverable. Coding time is tracked separately.', 11, MUTED, wrap=True))
        ly.addWidget(info); ly.addStretch(); return root

    # ---------------------------------------------------------------- focus

    def focus_page(self):
        root, ly = self.page_layout()
        ly.addWidget(section_title('Focus Timer', 'Start a session. Time is saved directly to the selected timed habit.'))
        cc, cl = card_layout(padding=(24, 22, 24, 22))
        timed = [h for h in self.store.habits() if h['kind'] == 'time']
        self.focus_picker = QComboBox()
        for h in timed:
            self.focus_picker.addItem(h['name'], h['id'])
        if self.focus_id is not None:
            idx = self.focus_picker.findData(self.focus_id)
            if idx >= 0:
                self.focus_picker.setCurrentIndex(idx)
        elif timed:
            self.focus_id = timed[0]['id']
        if not timed:
            self.focus_picker.addItem('No timed habits yet', None)
        self.focus_picker.setEnabled(bool(timed) and not self.session_active())
        self.focus_picker.currentIndexChanged.connect(self.pick_focus)
        picker_row = QWidget(); pl = QHBoxLayout(picker_row); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(12)
        pl.addWidget(label('TRACK TIME FOR', 9, MUTED, True, 1.6))
        pl.addWidget(self.focus_picker, 1)
        cl.addWidget(picker_row)
        if not timed:
            cl.addWidget(label('A focus session needs a timed habit. Create one below, then start the timer.', 11, MUTED, wrap=True))
            create = button('+ Create timed habit', True)
            create.clicked.connect(self.add_habit_dialog)
            cl.addWidget(create)
        self.timer_ring = TimerRing(246)
        self.timer_ring.set_running(self.started_wall is not None)
        ring_row = QHBoxLayout(); ring_row.addStretch(); ring_row.addWidget(self.timer_ring); ring_row.addStretch()
        cl.addSpacing(6); cl.addLayout(ring_row); cl.addSpacing(6)
        controls = QHBoxLayout(); controls.setSpacing(12)
        start = button('▶  Start / Resume', True)
        start.setEnabled(bool(timed) and self.started_wall is None)
        if not timed:
            start.setToolTip('Create a timed habit first.')
        start.clicked.connect(self.start_focus)
        pause = button('Ⅱ  Pause'); pause.setEnabled(self.started_wall is not None); pause.clicked.connect(self.pause_focus)
        stop = button('■  Stop && Save'); stop.setEnabled(self.session_active()); stop.clicked.connect(self.stop_focus)
        controls.addStretch(); controls.addWidget(start); controls.addWidget(pause); controls.addWidget(stop); controls.addStretch()
        cl.addLayout(controls)
        if self.session_active():
            saved = self.store.focus_state() or {}
            note = ('Running since ' + saved.get('segment_start', '')[:16].replace('T', ' ')) if saved.get('segment_start') else 'Paused session waiting for you.'
            cl.addWidget(label(note, 9, FAINT, wrap=True))
        ly.addWidget(cc)
        m, ml = card_layout(accent=CYAN); ml.addWidget(label('HOW TRACKING WORKS', 10, CYAN, True, 1.6))
        ml.addWidget(label('You can hide the main window while the timer runs. The system tray keeps Stay in Path active. '
                           'Press Stop & Save when finished; time is added to today’s log. '
                           'A running session is remembered, so sleep or a restart will not throw it away.', 11, MUTED, wrap=True))
        ly.addWidget(m); ly.addStretch(); return root

    def pick_focus(self, index):
        if self.focus_picker is not None and index >= 0 and self.started_wall is None and not self.paused:
            self.focus_id = self.focus_picker.itemData(index)

    def start_focus(self):
        if self.started_wall is not None:
            return
        if not self.paused:
            self.focus_id = self.focus_picker.currentData()
            self.running_seconds = 0.0
        if self.focus_id is None:
            QMessageBox.information(self, 'No timed habit', 'Add a timed habit first.'); return
        self.started_wall = datetime.now()
        self.paused = False
        self.persist_focus()
        self.refresh_page()
        self.notify('Focus started', 'Clock is running. You can minimize to the tray.', MINT)

    def pause_focus(self):
        if self.started_wall is None:
            return
        self.running_seconds = self.elapsed_seconds()
        self.started_wall = None
        self.paused = True
        self.persist_focus()
        self.refresh_page()

    def stop_focus(self):
        seconds = max(0, round(self.elapsed_seconds()))
        habit_id = self.focus_id
        if habit_id is not None and seconds > 0:
            try:
                self.store.add_focus(habit_id, seconds)
            except ValueError:
                seconds = 0
        self.clear_focus()
        self.refresh_views()
        if seconds > 0:
            self.notify('Session saved', f'{format_duration(seconds)} added to today.', MINT)

    def update_clock(self):
        secs = int(self.elapsed_seconds())
        if self.timer_ring is not None:
            self.timer_ring.set_seconds(secs)
            self.timer_ring.set_status('session running' if self.started_wall is not None
                                       else 'paused' if self.paused
                                       else 'ready')
        if self.side_focus is not None:
            if self.started_wall is not None:
                self.side_focus.setText(f'{secs // 60:02d}:{secs % 60:02d}  running')
            elif self.paused:
                self.side_focus.setText('paused')
            else:
                self.side_focus.setText('idle')

    # ---------------------------------------------------------------- weekly

    def weekly_page(self):
        root, ly = self.page_layout()
        info = self.store.weekly_review()
        ly.addWidget(section_title('Weekly Review', f'Monday {info["start"]} through {info["end"]} (so far)'))
        top = QWidget(); tl = QHBoxLayout(top); tl.setContentsMargins(0, 0, 0, 0); tl.setSpacing(16)
        consistency_card, ccl = card_layout(padding=(20, 18, 20, 18))
        level = info['completion'] / 100
        cring = Ring(level, 132, 9, 'consistency')
        cring.set_center_text(f'{info["completion"]}%')
        crow = QHBoxLayout(); crow.addStretch(); crow.addWidget(cring); crow.addStretch()
        ccl.addWidget(label('CONSISTENCY', 9, MUTED, True, 1.8))
        ccl.addLayout(crow)
        delta = info['completion'] - info['previous_completion']
        delta_label = label(f'{delta:+d} points vs last week', 10,
                            MINT if delta >= 0 else DANGER)
        # Without a minimum the label can be squeezed by the equal-width cards.
        delta_label.setMinimumWidth(delta_label.sizeHint().width())
        delta_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        ccl.addWidget(delta_label)
        tl.addWidget(consistency_card, 1)
        focus_card, fcl = card_layout(padding=(20, 18, 20, 18))
        fcl.addWidget(label('FOCUS THIS WEEK', 9, MUTED, True, 1.8))
        focus_num = AnimatedNumber(info['focus_minutes'], ' min', size=31, color=CYAN)
        fcl.addWidget(focus_num)
        fcl.addWidget(label(f'previous week  {info["previous_focus_minutes"]} min', 10, FAINT))
        week_values = list(self.store.calendar(7).values())
        fcl.addWidget(Sparkline(week_values, 38))
        fcl.addWidget(label('last 7 days', 9, FAINT))
        tl.addWidget(focus_card, 1)
        ly.addWidget(top)
        cc, cl = card_layout()
        cl.addWidget(label('HABIT COMPLETION THIS WEEK', 10, MUTED, True, 1.6))
        if not info['habit_rates']:
            cl.addWidget(label('Add habits to start generating reports.', 11, MUTED))
        for name, rate_value in info['habit_rates']:
            row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 4, 0, 4); rl.setSpacing(12)
            rl.addWidget(label(name, 12), 1)
            percent = label(f'{rate_value}%', 11, MINT, True)
            rl.addWidget(percent)
            cl.addWidget(row)
            cl.addWidget(AnimatedBar(rate_value / 100, 7))
        ly.addWidget(cc)
        pc, pl = card_layout(accent=CYAN); pl.addWidget(label('WEEK-TO-WEEK COMPARISON', 10, MUTED, True, 1.6))
        pl.addWidget(label(f'Previous week completion: {info["previous_completion"]}%', 11, MUTED))
        pl.addWidget(label(f'Previous week recorded focus: {info["previous_focus_minutes"]//60}h {info["previous_focus_minutes"]%60}m', 11, MUTED))
        pl.addWidget(label('Only elapsed days of the current week are included. Completion is the average of daily habit progress, capped at 100% per habit.', 10, FAINT, wrap=True))
        ly.addWidget(pc)
        ly.addStretch()
        return root


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow()
    if '--minimized' not in sys.argv:
        win.show()
    if not QSystemTrayIcon.isSystemTrayAvailable() and '--minimized' in sys.argv:
        win.show()
    exit_code = app.exec()
    win.close_store()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
