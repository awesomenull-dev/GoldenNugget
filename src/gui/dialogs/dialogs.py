from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QToolButton, QSizePolicy
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtCore import QSize

from webbrowser import open_new_tab

from src.controllers.web_request_handler import Nugget_Repo, get_latest_version

class PBHelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        QBtn = (
            QDialogButtonBox.Ok
        )
        self.buttonBox = QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)
        self.setWindowTitle(self.tr("PosterBoard Info"))

        layout = QVBoxLayout()
        message = QLabel(self.tr("Descriptors will be under the Collections section when adding a new wallpaper.\n\nIf the wallpapers don't appear in the menu, you either have to wait a bit for them to load,\nor you've reached the maximum amount of wallpapers (15) and have to wipe them."))
        layout.addWidget(message)

        imgBox = QWidget()
        imgBox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        imgBox.setStyleSheet("QWidget { background: none; padding: 0px; border: none; }")
        hlayout = QHBoxLayout()
        tut1 = QToolButton()
        tut1.setIconSize(QSize(138, 300))
        tut1.setStyleSheet("QToolButton { background: none; padding: 0px; border: none; }")
        tut1.setIcon(QIcon(QPixmap(":/gui/pb_tutorial1.png")))
        hlayout.addWidget(tut1)
        tut2 = QToolButton()
        tut2.setIconSize(QSize(138, 300))
        tut2.setStyleSheet("QToolButton { background: none; padding: 0px; border: none; }")
        tut2.setIcon(QIcon(QPixmap(":/gui/pb_tutorial2.png")))
        hlayout.addWidget(tut2)
        imgBox.setLayout(hlayout)

        layout.addWidget(imgBox)
        layout.addWidget(self.buttonBox)
        self.setLayout(layout)


from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QToolButton, QSizePolicy, QScrollArea, QFrame
from PySide6.QtGui import QFont, QIcon, QPixmap, QDesktopServices
from PySide6.QtCore import QSize, Qt, QUrl

from webbrowser import open_new_tab

from src.controllers.web_request_handler import Nugget_Repo, get_latest_version

# App version
from src.gui.version import App_Version, App_Build


class AboutProgramDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("About GoldenNugget"))
        self.setMinimumSize(500, 600)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QDialogButtonBox QPushButton {
                background-color: #007AFF;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                padding: 10px 24px;
                border: none;
            }
            QDialogButtonBox QPushButton:hover { background-color: #0066CC; }
        """)
        QBtn = QDialogButtonBox.Ok
        self.buttonBox = QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)
        
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # App icon and name
        header_layout = QHBoxLayout()
        header_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        icon_label = QLabel()
        icon_label.setPixmap(QPixmap(":/credits/big_nugget.png").scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header_layout.addWidget(icon_label)
        
        name_layout = QVBoxLayout()
        name_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        app_name = QLabel("GoldenNugget")
        app_name_font = QFont()
        app_name_font.setFamily("Unbounded")
        app_name_font.setPointSize(28)
        app_name_font.setBold(True)
        app_name.setFont(app_name_font)
        app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_layout.addWidget(app_name)
        
        version_str = f"v{App_Version}"
        if App_Build > 0:
            version_str += f" (beta {App_Build})"
        version_label = QLabel(version_str)
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("color: #8E8E93; font-size: 15px;")
        name_layout.addWidget(version_label)
        
        header_layout.addLayout(name_layout)
        layout.addLayout(header_layout)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #3A3A3C;")
        layout.addWidget(separator)
        
        # Description
        desc = QLabel(self.tr("Customize your iOS device with animated wallpapers, system tweaks, and more. Built for iOS 26.2+."))
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #EBEBF599; font-size: 15px; padding: 0 20px;")
        layout.addWidget(desc)
        
        # Credits section
        credits_title = QLabel(self.tr("Credits"))
        credits_title.setStyleSheet("font-size: 17px; font-weight: 600; color: #FFFFFF; padding-top: 8px;")
        layout.addWidget(credits_title)
        
        # Scrollable credits
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QWidget { background: transparent; }
            QScrollBar:vertical { width: 6px; background: transparent; }
            QScrollBar::handle { background: #3A3A3C; border-radius: 3px; min-height: 30px; }
        """)
        
        credits_widget = QWidget()
        credits_layout = QVBoxLayout(credits_widget)
        credits_layout.setSpacing(8)
        credits_layout.setContentsMargins(8, 8, 8, 8)
        
        # Credits data - from original home page
        credits = [
            ("Main Developer", "awesomenull", "https://github.com/awesomenull-dev"),
            ("Co-Developer", "Wind0ws11Aero", "https://github.com/Wind0ws11Aero"),
            ("Nugget Creator", "leminlemiz", "https://github.com/leminlemiz"),
            ("PosterRestore Team", "PosterRestore Discord", "https://discord.gg/gWtzTVhMvh"),
            ("PosterBoard Help", "dootskyre, Middo, dulark, forcequitOS, pingubow", "https://twitter.com/dootskyre"),
            ("Wallpaper Website", "SerStars", "https://cowabun.ga/wallpapers"),
            ("Global Flags", "disfordottie", "https://twitter.com/disfordottie"),
            ("Springboard/Internal", "iTechExpert", "https://twitter.com/iTechExpert21"),
            ("Quiet Daemon", "Mikasa-san", "https://github.com/Mikasa-san/QuietDaemon"),
            ("pymobiledevice3", "doronz88", "https://github.com/doronz88/pymobiledevice3"),
            ("PySide6", "Qt Company", "https://doc.qt.io/qtforpython-6/"),
            ("AAR Handling", "Snoolie", "https://github.com/0xilis/python-aar-stuff"),
            ("AI Eligibility", "f1shy-dev", "https://github.com/f1shy-dev"),
            ("PosterBoard Icons", "JJTech", "https://github.com/JJTech0130"),
        ]
        
        for title, name, url in credits:
            item = QWidget()
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            
            title_label = QLabel(f"{title}:")
            title_label.setStyleSheet("color: #EBEBF599; font-size: 14px; font-weight: 500; min-width: 160px;")
            item_layout.addWidget(title_label)
            
            name_btn = QToolButton()
            name_btn.setText(name)
            name_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            name_btn.setStyleSheet("""
                QToolButton { 
                    color: #007AFF; 
                    font-size: 14px; 
                    background: none; 
                    border: none; 
                    padding: 0; 
                    text-align: left;
                }
                QToolButton:hover { color: #0066CC; text-decoration: underline; }
            """)
            name_btn.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
            item_layout.addWidget(name_btn)
            item_layout.addStretch()
            
            credits_layout.addWidget(item)
        
        scroll.setWidget(credits_widget)
        layout.addWidget(scroll, 1)
        
        # Links
        links_layout = QHBoxLayout()
        links_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        links_layout.setSpacing(24)
        
        github_btn = QToolButton()
        github_btn.setText("GitHub")
        github_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        github_btn.setStyleSheet("QToolButton { color: #007AFF; font-size: 14px; font-weight: 500; background: none; border: none; padding: 4px 8px; } QToolButton:hover { text-decoration: underline; }")
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/awesomenull-dev/GoldenNugget")))
        links_layout.addWidget(github_btn)
        
        website_btn = QToolButton()
        website_btn.setText("Wallpapers")
        website_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        website_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        website_btn.setStyleSheet("QToolButton { color: #007AFF; font-size: 14px; font-weight: 500; background: none; border: none; padding: 4px 8px; } QToolButton:hover { text-decoration: underline; }")
        website_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://cowabun.ga/wallpapers")))
        links_layout.addWidget(website_btn)
        
        discord_btn = QToolButton()
        discord_btn.setText("Discord")
        discord_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        discord_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        discord_btn.setStyleSheet("QToolButton { color: #007AFF; font-size: 14px; font-weight: 500; background: none; border: none; padding: 4px 8px; } QToolButton:hover { text-decoration: underline; }")
        discord_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://discord.gg/RwbtH7pW5e")))
        links_layout.addWidget(discord_btn)
        
        layout.addLayout(links_layout)
        layout.addWidget(self.buttonBox)
        self.setLayout(layout)


class UpdateAppDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        QBtn = (
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )

        self.buttonBox = QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        layout = QVBoxLayout()
        title = QLabel(self.tr("Update Available"))
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)

        message_text = ""
        latest_version = get_latest_version()
        if latest_version != None:
            message_text += self.tr("Nugget v{0} is available. ").format(latest_version)
        message_text += self.tr("Would you like to go to the download on GitHub?")
        message = QLabel(message_text)

        layout.addWidget(title)
        layout.addWidget(message)
        layout.addWidget(self.buttonBox)
        self.setLayout(layout)

    def accept(self):
        # open up the repo page
        open_new_tab(f"https://github.com/{Nugget_Repo}")
        super().accept()