"""Stay in Path - private, offline Windows habit tracker and desktop widget."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from storage import Store, data_dir

APP_TITLE = 'Stay in Path'
GREEN = '#65e6a0'
DARK = '#10171d'
MUTED = '#9baeb8'
DAY_COLORS = ['#243039', '#164e37', '#22784d', '#32a66b', '#65e6a0']


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


def label(text: str, size: int = 11, color: str = '#e8f6ee', bold: bool = False):
    w = QLabel(text)
    w.setWordWrap(True)
    w.setStyleSheet(f'color:{color}; font-size:{size}px; font-weight:{700 if bold else 400}; background:transparent;')
    return w


def button(text: str, primary: bool = False):
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        b.setProperty('primary', True)
    return b


def card_layout():
    card = QFrame()
    card.setObjectName('card')
    ly = QVBoxLayout(card)
    ly.setContentsMargins(19, 17, 19, 17)
    ly.setSpacing(12)
    return card, ly


def section_title(title: str, description: str = ''):
    box = QWidget()
    ly = QVBoxLayout(box)
    ly.setContentsMargins(0, 2, 0, 6)
    ly.setSpacing(3)
    ly.addWidget(label(title, 22, '#ffffff', True))
    if description:
        ly.addWidget(label(description, 11, MUTED))
    return box


def hrow(*widgets, stretch=False):
    host = QWidget()
    ly = QHBoxLayout(host)
    ly.setContentsMargins(0, 0, 0, 0)
    ly.setSpacing(12)
    for w in widgets:
        ly.addWidget(w)
    if stretch:
        ly.addStretch()
    return host


class Heatmap(QWidget):
    """A 13-week GitHub-like contribution heatmap for one or all habits."""
    def __init__(self, calendar: dict[str, float | None], compact: bool = False, parent=None):
        super().__init__(parent)
        self.data = calendar
        self.compact = compact
        self.setMinimumHeight(174 if compact else 193)
        self.setMouseTracking(True)
        self.positions = []

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        keys = sorted(self.data.keys())
        if not keys:
            return
        first = date.fromisoformat(keys[0]); last = date.fromisoformat(keys[-1])
        start = first - timedelta(days=first.weekday())
        cols = ((last-start).days // 7) + 1
        left, top, gap = (4, 12, 4) if self.compact else (48, 24, 5)
        available = max(8, self.width() - left - 6)
        cell = min(18 if not self.compact else 14, max(5, int(available / cols) - gap))
        self.positions = []
        if not self.compact:
            painter.setPen(QColor(MUTED))
            painter.setFont(QFont('Segoe UI', 9))
            for idx, txt in [(0, 'Mon'), (2, 'Wed'), (4, 'Fri')]:
                painter.drawText(4, top + idx*(cell+gap) + cell, txt)
            painter.setPen(Qt.PenStyle.NoPen)
        for key in keys:
            d = date.fromisoformat(key)
            col = (d - start).days // 7
            row = d.weekday()
            x = left + col * (cell + gap)
            y = top + row * (cell + gap)
            val = self.data[key]
            color = '#20272f' if val is None else DAY_COLORS[0 if val == 0 else min(4, max(1, int(val*4 + .999)))]
            painter.setBrush(QBrush(QColor(color)))
            rect = QRectF(x, y, cell, cell)
            painter.drawRoundedRect(rect, 3, 3)
            self.positions.append((rect, key, val))
        if not self.compact:
            painter.setPen(QColor(MUTED))
            painter.drawText(left, self.height() - 7, 'Less   ▪  ▪  ▪  ▪  ▪   More   ·  gray = not tracked')

    def mouseMoveEvent(self, event):
        from PySide6.QtWidgets import QToolTip
        pos = event.position()
        for rect, day, v in self.positions:
            if rect.contains(pos):
                QToolTip.showText(event.globalPosition().toPoint(), f'{day}  •  {"Not tracked" if v is None else str(round(v*100))+"% complete"}', self)
                return
        QToolTip.hideText()


class DesktopWidget(QWidget):
    """Movable always-on-top mini gadget (not a Windows Explorer embedded gadget)."""
    def __init__(self, app_window):
        super().__init__()
        self.owner = app_window
        self.setWindowTitle('Stay in Path Widget')
        self.setWindowIcon(app_window.app_icon)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(378)
        self.drag_pos = None
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(4, 4, 4, 4)
        self.refresh()
        pos = app_window.store.setting('widget_position')
        if pos and ',' in pos:
            try:
                x,y = map(int, pos.split(',')); self.move(x,y)
            except (TypeError, ValueError):
                pass
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.right()-self.width()-18, screen.top()+45)

    def refresh(self):
        while self.root.count():
            item = self.root.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        panel, ly = card_layout()
        panel.setStyleSheet('QFrame#card { background:#111c22; border:1px solid #34564b; border-radius:17px; }')
        header = QWidget(); row = QHBoxLayout(header); row.setContentsMargins(0,0,0,0)
        row.addWidget(label('◈  STAY IN PATH', 13, GREEN, True)); row.addStretch()
        open_b = button('↗'); open_b.setFixedWidth(34); open_b.setToolTip('Open dashboard')
        open_b.clicked.connect(lambda: self.owner.show_page('Dashboard'))
        hide_b = button('×'); hide_b.setFixedWidth(34); hide_b.setToolTip('Hide widget')
        hide_b.clicked.connect(self.hide_widget)
        row.addWidget(open_b); row.addWidget(hide_b); ly.addWidget(header)
        mission = self.owner.store.get_mission()
        ly.addWidget(label('MAIN MISSION', 9, MUTED, True))
        ly.addWidget(label(mission['title'], 12, '#ffffff', True))
        bar = QProgressBar(); bar.setRange(0,max(1,mission['total'])); bar.setValue(mission['completed']); bar.setTextVisible(True)
        ly.addWidget(bar)
        s, longest = self.owner.store.streaks()
        ly.addWidget(label(f'🔥  {s} day streak     •     Best {longest} days', 11, '#d9f5e7', True))
        ly.addWidget(Heatmap(self.owner.store.calendar(91), compact=True))
        habits = self.owner.store.habits()
        if not habits:
            ly.addWidget(label('Add your first habit from the dashboard.', 11, MUTED))
        for h in habits[:4]:
            value = self.owner.store.log_value(h['id'])
            rr = QWidget(); hly = QHBoxLayout(rr); hly.setContentsMargins(0,0,0,0)
            hly.addWidget(label(h['name'][:26], 11))
            hly.addStretch()
            if h['kind'] == 'yesno':
                check = QCheckBox(); check.setChecked(value >= 1)
                check.toggled.connect(lambda checked, hid=h['id']: self.owner.update_log(hid, 1 if checked else 0))
                hly.addWidget(check)
            else:
                hly.addWidget(label(f'{int(value)}/{h["goal_minutes"]} min', 10, GREEN))
            ly.addWidget(rr)
        if len(habits)>4:
            ly.addWidget(label(f'+ {len(habits)-4} more habits in app', 10, MUTED))
        focus = button('▶  Open focus timer', True)
        focus.clicked.connect(lambda: self.owner.show_page('Focus Timer'))
        ly.addWidget(focus)
        self.root.addWidget(panel)
        self.adjustSize()

    def hide_widget(self):
        self.hide()
        self.owner.store.save_setting('widget_visible','0')
        self.owner.update_widget_action()

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
    NAV = ('Dashboard','Habits','Main Mission','Focus Timer','Weekly Review')

    def __init__(self):
        super().__init__()
        self.store = Store()
        self.app_icon = QIcon(str(asset_path('stay-in-path.png')))
        self.setWindowIcon(self.app_icon)
        self.setWindowTitle('Stay in Path — Consistency makes progress')
        self.resize(1040, 740)
        self.setMinimumSize(790, 580)
        self.focus_id = None
        self.running_seconds = 0.0
        self.started_at = None
        self.paused = False
        self.page_name = 'Dashboard'
        self.timer_label = None
        self.timer_status = None
        self.focus_picker = None
        self.widget = None
        self.really_quit = False
        self.setup_ui()
        self.setup_tray()
        self.widget = DesktopWidget(self)
        if self.store.setting('widget_visible','1') != '0':
            self.widget.show()
        self.update_widget_action()
        self.show_page('Dashboard', reveal=False)
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.update_clock)
        self.clock.start(1000)
        self.refresh_clock = QTimer(self)
        self.refresh_clock.timeout.connect(self.refresh_views)
        self.refresh_clock.start(60000)

    def setup_ui(self):
        QApplication.instance().setStyleSheet('''
            QWidget { background: #10171d; color: #e7f1ee; font: 11pt 'Segoe UI'; }
            QFrame#card { background: #19242b; border: 1px solid #2b3a42; border-radius: 14px; }
            QFrame#sidebar { background: #121d23; border-right:1px solid #293941; }
            QPushButton { padding: 9px 13px; background:#273840; border:1px solid #354951; border-radius:8px; font-weight:600; }
            QPushButton:hover { background:#345047; }
            QPushButton[primary="true"] { background:#65e6a0; color:#09241a; border:1px solid #65e6a0; }
            QPushButton[primary="true"]:hover { background:#93f2bc; }
            QLineEdit, QSpinBox, QComboBox { background:#101b21; border:1px solid #3b4c53; border-radius:7px; padding:7px; min-height:22px; }
            QProgressBar { background:#25353b; border:none; border-radius:6px; height:13px; text-align:center; }
            QProgressBar::chunk { background:#65e6a0; border-radius:6px; }
            QCheckBox { spacing:8px; }
            QCheckBox::indicator { width:19px; height:19px; }
            QScrollArea { border:none; }
            QScrollBar:vertical { background:#142127; width:10px; }
            QScrollBar::handle:vertical { background:#3c5850; border-radius:5px; }
        ''')
        central = QWidget(); self.setCentralWidget(central)
        lay = QHBoxLayout(central); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        sidebar = QFrame(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(206)
        side = QVBoxLayout(sidebar); side.setContentsMargins(15,22,15,18); side.setSpacing(9)
        brand = QWidget(); header = QHBoxLayout(brand); header.setContentsMargins(2,0,0,16)
        brand_icon = QLabel(); brand_icon.setPixmap(self.app_icon.pixmap(QSize(38,38)))
        header.addWidget(brand_icon)
        header.addWidget(label('STAY IN\nPATH', 14, GREEN, True)); header.addStretch()
        side.addWidget(brand)
        self.nav_buttons = {}
        symbols = {'Dashboard':'▦','Habits':'✓','Main Mission':'◎','Focus Timer':'◷','Weekly Review':'▥'}
        for name in self.NAV:
            b = button(f'{symbols[name]}   {name}')
            b.setStyleSheet('text-align:left; padding:13px 11px;')
            b.clicked.connect(lambda _=False, n=name: self.show_page(n))
            side.addWidget(b)
            self.nav_buttons[name] = b
        side.addStretch()
        hint = label('Your path. Your pace.\nAll data stays on this PC.',10,MUTED)
        side.addWidget(hint)
        lay.addWidget(sidebar)
        self.pages = QStackedWidget()
        lay.addWidget(self.pages, 1)

    def setup_tray(self):
        self.tray = QSystemTrayIcon(self.app_icon, self)
        menu = QMenu()
        menu.addAction('Open Stay in Path',lambda: self.show_page('Dashboard'))
        self.widget_action = menu.addAction('Show desktop widget', self.toggle_widget)
        menu.addSeparator()
        menu.addAction('Quit completely',self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip('Stay in Path — offline habit tracker')
        self.tray.activated.connect(lambda reason: self.show_page('Dashboard') if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def update_widget_action(self):
        if self.widget is not None:
            self.widget_action.setText('Hide desktop widget' if self.widget.isVisible() else 'Show desktop widget')

    def set_widget_visible(self, shown: bool):
        if shown != self.widget.isVisible():
            self.toggle_widget()

    def set_autostart(self, enabled: bool):
        try:
            configure_autostart(enabled)
        except OSError as exc:
            QMessageBox.warning(self, 'Startup setting failed', str(exc))
        self.refresh_page()

    def toggle_widget(self):
        if self.widget.isVisible():
            self.widget.hide_widget()
        else:
            self.widget.refresh(); self.widget.show(); self.widget.raise_()
            self.store.save_setting('widget_visible','1')
            self.update_widget_action()

    def quit_app(self):
        if self.started_at is not None or self.paused:
            answer = QMessageBox.question(self, 'Unsaved timer', 'A focus session is running or paused. Quit and discard it?')
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.really_quit = True
        self.tray.hide()
        self.widget.close()
        self.store.close()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self.really_quit:
            event.accept()
        elif QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            self.tray.showMessage(APP_TITLE, 'Still running in the tray. Use Quit to exit.', QSystemTrayIcon.MessageIcon.Information, 2000)
        else:
            if self.started_at is not None or self.paused:
                event.ignore()
                self.quit_app()
            else:
                self.really_quit = True
                self.widget.close()
                self.store.close()
                event.accept()
                QTimer.singleShot(0, QApplication.instance().quit)

    def show_page(self, name: str, reveal: bool = True):
        self.page_name = name
        self.refresh_page()
        for n,b in self.nav_buttons.items():
            b.setProperty('selected', n == name)
            b.setStyleSheet('text-align:left; padding:13px 11px;' +
                            ('background:#234938; border:1px solid #38885c; color:#9af2bf;' if n==name else ''))
        if reveal:
            self.showNormal(); self.raise_(); self.activateWindow()

    def refresh_page(self):
        self.timer_label = None
        self.timer_status = None
        self.focus_picker = None
        builders = {
            'Dashboard':self.dashboard, 'Habits':self.habits_page,
            'Main Mission':self.mission_page,'Focus Timer':self.focus_page,
            'Weekly Review':self.weekly_page,
        }
        new_page = self.scroller(builders[self.page_name]())
        old = self.pages.currentWidget()
        self.pages.addWidget(new_page); self.pages.setCurrentWidget(new_page)
        if old is not None:
            self.pages.removeWidget(old); old.deleteLater()

    @staticmethod
    def scroller(content: QWidget):
        area = QScrollArea(); area.setWidgetResizable(True); area.setWidget(content)
        return area

    def refresh_views(self):
        self.refresh_page()
        if self.widget:
            self.widget.refresh()

    def page_layout(self):
        root = QWidget(); root.setObjectName('page')
        ly = QVBoxLayout(root); ly.setContentsMargins(28,28,28,28); ly.setSpacing(16)
        return root,ly

    def dashboard(self):
        root,ly = self.page_layout()
        ly.addWidget(section_title('Dashboard', 'Show up consistently. Make meaningful progress.'))
        mission = self.store.get_mission()
        mc,ml = card_layout()
        ml.addWidget(label('◎  MAIN MISSION',11,GREEN,True))
        ml.addWidget(label(mission['title'],19,'#ffffff',True))
        prog = QProgressBar(); prog.setRange(0,mission['total']); prog.setValue(mission['completed']); prog.setFormat('%p%')
        ml.addWidget(prog)
        if mission['deadline']:
            ml.addWidget(label('Deadline  ' + mission['deadline'],10,MUTED))
        modify=button('Edit mission'); modify.clicked.connect(lambda: self.show_page('Main Mission'))
        ml.addWidget(modify)
        ly.addWidget(mc)
        current,longest = self.store.streaks()
        grid = QGridLayout(); grid.setSpacing(12)
        today_values = self.store.calendar(1)
        rate = next(iter(today_values.values()))
        for i,(cap,value) in enumerate([('CURRENT STREAK',f'{current} days'),('LONGEST STREAK',f'{longest} days'),('TODAY', f'{round(rate*100)}%' if rate is not None else '—')]):
            cc,cl=card_layout();cl.addWidget(label(cap,10,MUTED,True));cl.addWidget(label(value,22,GREEN,True));grid.addWidget(cc,0,i)
        ly.addLayout(grid)
        hc,hl=card_layout();hl.addWidget(label('CONSISTENCY  ·  LAST 13 WEEKS',11,'#ffffff',True))
        hl.addWidget(Heatmap(self.store.calendar(91)))
        ly.addWidget(hc)
        habits = self.store.habits()
        cc,cl=card_layout()
        title_row = QWidget(); hr=QHBoxLayout(title_row);hr.setContentsMargins(0,0,0,0)
        hr.addWidget(label('TODAY’S HABITS',12,'#ffffff',True));hr.addStretch()
        add=button('+ Add habit',True);add.clicked.connect(self.add_habit_dialog);hr.addWidget(add)
        cl.addWidget(title_row)
        if not habits:
            cl.addWidget(label('No habits yet. Create a Yes/No or timed habit to begin.',11,MUTED))
        for h in habits:
            cl.addWidget(self.habit_row(h))
        ly.addWidget(cc)
        settings,sl = card_layout()
        sl.addWidget(label('DESKTOP & STARTUP',11,'#ffffff',True))
        wcheck=QCheckBox('Show floating desktop widget')
        wcheck.setChecked(self.widget.isVisible() if self.widget is not None else True)
        wcheck.toggled.connect(lambda checked: self.set_widget_visible(checked))
        sl.addWidget(wcheck)
        acheck=QCheckBox('Start with Windows')
        acheck.setEnabled(os.name == 'nt')
        acheck.setChecked(is_autostart_enabled())
        acheck.toggled.connect(self.set_autostart)
        sl.addWidget(acheck)
        ly.addWidget(settings)
        ly.addStretch()
        return root

    def habit_row(self,h):
        container=QWidget();line=QHBoxLayout(container);line.setContentsMargins(0,4,0,4);line.setSpacing(12)
        line.addWidget(label(h['name'],12,'#f2fff8',True),1)
        value=self.store.log_value(h['id'])
        if h['kind']=='yesno':
            toggle=QCheckBox('Done');toggle.setChecked(value>=1)
            toggle.toggled.connect(lambda checked,hid=h['id']: self.update_log(hid,1 if checked else 0))
            line.addWidget(toggle)
        else:
            line.addWidget(label(f'/ {h["goal_minutes"]} min',10,MUTED))
            spin=QSpinBox();spin.setRange(0,9999);spin.setSuffix(' min');spin.setValue(round(value));spin.setFixedWidth(115)
            spin.setToolTip('Manual total minutes today. Focus sessions also add time.')
            spin.editingFinished.connect(lambda hid=h['id'], control=spin: self.update_log(hid,control.value()))
            line.addWidget(spin)
        return container

    def update_log(self,habit_id:int,value:float):
        self.store.set_log(habit_id,value)
        # Keep widgets and metric cards in sync after each edit.
        if self.page_name in ('Dashboard','Habits','Weekly Review'):
            self.refresh_page()
        if self.widget:
            self.widget.refresh()

    def habits_page(self):
        root,ly=self.page_layout()
        ly.addWidget(section_title('Habits','Each habit has its own contribution graph and streak.'))
        add=button('+ New habit',True);add.clicked.connect(self.add_habit_dialog);ly.addWidget(add)
        habits=self.store.habits()
        if not habits:
            ly.addWidget(label('Add your first habit to see the individual heatmap.',12,MUTED))
        for h in habits:
            cc,cl=card_layout();heading=QWidget();hr=QHBoxLayout(heading);hr.setContentsMargins(0,0,0,0)
            hr.addWidget(label(h['name'],16,'#ffffff',True));hr.addStretch()
            rm=button('Archive');rm.setToolTip('Hide the habit without deleting its history')
            rm.clicked.connect(lambda _=False,hid=h['id'],n=h['name']: self.archive_habit(hid,n))
            hr.addWidget(rm);cl.addWidget(heading)
            current,best=self.store.streaks(h['id'])
            ty = 'Yes/No habit' if h['kind']=='yesno' else f'Timed habit · {h["goal_minutes"]} min/day'
            cl.addWidget(label(f'{ty}   •   Current streak: {current} days   •   Best: {best} days',10,MUTED))
            cl.addWidget(Heatmap(self.store.calendar(91,h['id'])))
            cl.addWidget(self.habit_row(h))
            ly.addWidget(cc)
        ly.addStretch();return root

    def add_habit_dialog(self):
        dlg=QDialog(self);dlg.setWindowTitle('Create habit');dlg.setMinimumWidth(360)
        form=QFormLayout(dlg);form.setSpacing(12)
        title=QLineEdit();title.setPlaceholderText('e.g. Build my app')
        kind=QComboBox();kind.addItems(['Yes / No','Time (minutes)'])
        goal=QSpinBox();goal.setRange(1,1440);goal.setValue(60);goal.setSuffix(' min/day')
        form.addRow('Habit name:',title);form.addRow('Type:',kind);form.addRow('Daily target:',goal)
        goal.setEnabled(False)
        kind.currentIndexChanged.connect(lambda i: goal.setEnabled(i==1))
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(dlg.accept);controls.rejected.connect(dlg.reject)
        form.addRow(controls)
        if dlg.exec()==QDialog.DialogCode.Accepted:
            try:
                self.store.add_habit(title.text(),'time' if kind.currentIndex()==1 else 'yesno',goal.value())
                self.refresh_views()
            except ValueError as err:
                QMessageBox.warning(self,'Invalid habit',str(err))

    def archive_habit(self,habit_id:int,name:str):
        if habit_id==self.focus_id and (self.started_at is not None or self.paused):
            QMessageBox.information(self,'Timer active','Stop and save your current focus session first.')
            return
        if QMessageBox.question(self,'Archive habit',f'Archive “{name}”? Existing history remains saved.')==QMessageBox.StandardButton.Yes:
            self.store.delete_habit(habit_id)
            if self.focus_id==habit_id:self.focus_id=None
            self.refresh_views()

    def mission_page(self):
        root,ly=self.page_layout()
        ly.addWidget(section_title('Main Mission','Keep one meaningful goal in front of you.'))
        cc,cl=card_layout();m=self.store.get_mission()
        cl.addWidget(label('MISSION TITLE',10,MUTED,True))
        title=QLineEdit(m['title']);title.setMaxLength(140);cl.addWidget(title)
        cl.addWidget(label('MILESTONES / STEPS',10,MUTED,True))
        hr=QHBoxLayout();done=QSpinBox();done.setRange(0,9999);done.setValue(m['completed'])
        total=QSpinBox();total.setRange(1,9999);total.setValue(m['total']);hr.addWidget(label('Completed'));hr.addWidget(done)
        hr.addWidget(label('Total'));hr.addWidget(total);cl.addLayout(hr)
        cl.addWidget(label('OPTIONAL DEADLINE (YYYY-MM-DD)',10,MUTED,True))
        deadline=QLineEdit(m['deadline']);deadline.setPlaceholderText('e.g. 2026-12-15');cl.addWidget(deadline)
        save=button('Save mission',True)
        def save_mission():
            try:
                self.store.save_mission(title.text(),done.value(),total.value(),deadline.text().strip())
            except (ValueError,OverflowError) as err:
                QMessageBox.warning(self,'Invalid mission',str(err));return
            self.refresh_views()
        save.clicked.connect(save_mission);cl.addWidget(save)
        ly.addWidget(cc)
        info,il=card_layout();il.addWidget(label('Progress ≠ time spent',12,GREEN,True))
        il.addWidget(label('Mark a milestone completed only when you finish a real deliverable. Coding time is tracked separately.',11,MUTED))
        ly.addWidget(info);ly.addStretch();return root

    def focus_page(self):
        root,ly=self.page_layout()
        ly.addWidget(section_title('Focus Timer','Start a session. Time is saved directly to the selected timed habit.'))
        cc,cl=card_layout()
        cl.addWidget(label('TRACK TIME FOR',10,MUTED,True))
        self.focus_picker=QComboBox()
        timed=[h for h in self.store.habits() if h['kind']=='time']
        for h in timed:
            self.focus_picker.addItem(h['name'],h['id'])
        if self.focus_id is not None:
            idx=self.focus_picker.findData(self.focus_id)
            if idx>=0:self.focus_picker.setCurrentIndex(idx)
        elif timed:
            self.focus_id=timed[0]['id']
        self.focus_picker.setEnabled(self.started_at is None and not self.paused)
        self.focus_picker.currentIndexChanged.connect(self.pick_focus)
        cl.addWidget(self.focus_picker)
        if not timed:
            cl.addWidget(label('Create a time-based habit before starting a focus session.',11,MUTED))
        self.timer_label=label('',47,GREEN,True);self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.timer_label)
        self.timer_status=label('',11,MUTED);self.timer_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.timer_status)
        controls=QHBoxLayout()
        start=button('▶  Start / Resume',True);start.setEnabled(bool(timed) and self.started_at is None)
        start.clicked.connect(self.start_focus)
        pause=button('Ⅱ  Pause');pause.setEnabled(self.started_at is not None);pause.clicked.connect(self.pause_focus)
        stop=button('■  Stop & Save');stop.setEnabled(self.started_at is not None or self.paused);stop.clicked.connect(self.stop_focus)
        controls.addWidget(start);controls.addWidget(pause);controls.addWidget(stop)
        cl.addLayout(controls);ly.addWidget(cc)
        m,ml=card_layout();ml.addWidget(label('HOW TRACKING WORKS',11,GREEN,True))
        ml.addWidget(label('You can hide the main window while the timer runs. The system tray keeps Stay in Path active. Press Stop & Save when finished; time is added to today’s log.',11,MUTED))
        ly.addWidget(m);ly.addStretch();self.update_clock();return root

    def pick_focus(self,index):
        if self.focus_picker is not None and index>=0 and self.started_at is None and not self.paused:
            self.focus_id=self.focus_picker.itemData(index)

    def start_focus(self):
        if self.started_at is not None:
            return
        if not self.paused:
            self.focus_id=self.focus_picker.currentData()
            self.running_seconds=0.0
        if self.focus_id is None:
            QMessageBox.information(self,'No timed habit','Add a timed habit first.');return
        self.started_at=time.monotonic();self.paused=False
        self.refresh_page()

    def elapsed_seconds(self):
        return self.running_seconds + (time.monotonic()-self.started_at if self.started_at is not None else 0)

    def pause_focus(self):
        if self.started_at is None:return
        self.running_seconds=self.elapsed_seconds();self.started_at=None;self.paused=True
        self.refresh_page()

    def stop_focus(self):
        seconds=max(0,round(self.elapsed_seconds()))
        if self.focus_id is not None and seconds > 0:
            self.store.add_focus(self.focus_id,seconds)
        self.running_seconds=0.0;self.started_at=None;self.paused=False
        self.refresh_views()
        if seconds>0:
            self.tray.showMessage(APP_TITLE,f'Saved {seconds // 60}m {seconds % 60}s to today.',QSystemTrayIcon.MessageIcon.Information,2500)

    def update_clock(self):
        secs=int(self.elapsed_seconds())
        if self.timer_label is not None:
            self.timer_label.setText(f'{secs//3600:02d}:{secs//60%60:02d}:{secs%60:02d}')
        if self.timer_status is not None:
            self.timer_status.setText('FOCUS IN PROGRESS' if self.started_at is not None else 'PAUSED — NOT YET SAVED' if self.paused else 'READY WHEN YOU ARE')

    def weekly_page(self):
        root,ly=self.page_layout()
        info=self.store.weekly_review()
        ly.addWidget(section_title('Weekly Review',f'Monday {info["start"]} through {info["end"]} (so far)'))
        grid=QGridLayout();grid.setSpacing(12)
        values=[('CONSISTENCY',f'{info["completion"]}%'),('FOCUS TIME',f'{info["focus_minutes"]//60}h {info["focus_minutes"]%60}m'),
                ('VS LAST WEEK',f'{info["completion"]-info["previous_completion"]:+d} points')]
        for i,(name,value) in enumerate(values):
            c,l=card_layout();l.addWidget(label(name,10,MUTED,True));l.addWidget(label(value,22,GREEN,True));grid.addWidget(c,0,i)
        ly.addLayout(grid)
        cc,cl=card_layout()
        cl.addWidget(label('HABIT COMPLETION THIS WEEK',12,'#ffffff',True))
        if not info['habit_rates']:
            cl.addWidget(label('Add habits to start generating reports.',11,MUTED))
        for name,rate in info['habit_rates']:
            cl.addWidget(label(f'{name} — {rate}%',11))
            bar=QProgressBar();bar.setRange(0,100);bar.setValue(rate);bar.setTextVisible(False)
            cl.addWidget(bar)
        ly.addWidget(cc)
        pc,pl=card_layout();pl.addWidget(label('WEEK-TO-WEEK COMPARISON',12,'#ffffff',True))
        pl.addWidget(label(f'Previous week completion: {info["previous_completion"]}%',11,MUTED))
        pl.addWidget(label(f'Previous week recorded focus: {info["previous_focus_minutes"]//60}h {info["previous_focus_minutes"]%60}m',11,MUTED))
        pl.addWidget(label('Only elapsed days of the current week are included. Completion is the average of daily habit progress, capped at 100% per habit.',10,MUTED))
        ly.addWidget(pc)
        ly.addStretch()
        return root


def main():
    app=QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setQuitOnLastWindowClosed(False)
    win=MainWindow()
    if '--minimized' not in sys.argv:
        win.show()
    if not QSystemTrayIcon.isSystemTrayAvailable() and '--minimized' in sys.argv:
        win.show()
    exit_code=app.exec()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
