"""Component stylesheet templates with ``{slot}`` placeholders.

Usage::

    from src.gui.theme.styles import STYLES
    widget.setStyleSheet(STYLES["card"].format_map(theme.colors.__dict__))
"""


STYLES = {
    # ---- Components ------------------------------------------------------
    "text_input_dialog": """
        QDialog {{ background-color: {bg_elevated}; }}
        QLabel {{ color: {text_primary}; font-size: 15px; }}
        QLineEdit {{
            background-color: {bg_input};
            border: none;
            border-radius: 10px;
            color: {text_primary};
            font-size: 15px;
            padding: 12px 16px;
        }}
        QPushButton {{
            background-color: {accent};
            border-radius: 10px;
            color: {text_inverse};
            font-size: 15px;
            font-weight: 600;
            padding: 12px 24px;
            border: none;
            min-width: 80px;
        }}
        QPushButton:hover {{ background-color: {accent_hover}; }}
    """,

    "number_input_dialog": """
        QDialog {{ background-color: {bg_elevated}; }}
        QLabel {{ color: {text_primary}; font-size: 15px; }}
        QSpinBox {{
            background-color: {bg_input};
            border: none;
            border-radius: 10px;
            color: {text_primary};
            font-size: 15px;
            padding: 12px 16px;
        }}
        QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}
        QPushButton {{
            background-color: {accent};
            border-radius: 10px;
            color: {text_inverse};
            font-size: 15px;
            font-weight: 600;
            padding: 12px 24px;
            border: none;
            min-width: 80px;
        }}
        QPushButton:hover {{ background-color: {accent_hover}; }}
    """,

    "section_header": (
        "font-size: 13px; font-weight: 600; color: {text_secondary}; "
        "text-transform: uppercase; letter-spacing: 0.5px; padding-left: 4px;"
    ),

    "card": """
        IOSCard {{
            background-color: {bg_secondary};
            border-radius: 12px;
            border: none;
        }}
    """,

    "nav_bar": "background-color: {bg_secondary}; border-bottom: 1px solid {divider};",

    "nav_back_btn": """
        QPushButton {{
            background: transparent;
            color: {accent};
            font-size: 17px;
            font-weight: 400;
            border: none;
            padding: 8px 0;
        }}
        QPushButton:hover {{ color: {accent_hover}; }}
    """,

    "nav_title": "font-size: 17px; font-weight: 600; color: {text_primary};",

    "nav_right_btn": """
        QPushButton {{
            background: transparent;
            color: {accent};
            font-size: 15px;
            font-weight: 600;
            border: none;
            padding: 8px 0;
        }}
        QPushButton:hover {{ color: {accent_hover}; }}
    """,

    "settings_row": """
        QPushButton {{
            background-color: {bg_secondary};
            border-radius: 10px;
            color: {text_primary};
            font-size: 15px;
            text-align: left;
            padding: 14px 16px;
            border: none;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    "primary_button": """
        QPushButton {{
            background-color: {accent};
            border-radius: 12px;
            color: {text_inverse};
            font-size: 17px;
            font-weight: 600;
            border: none;
        }}
        QPushButton:hover {{ background-color: {accent_hover}; }}
        QPushButton:pressed {{ background-color: {accent_pressed}; }}
        QPushButton:disabled {{ background-color: {border}; color: {text_disabled}; }}
    """,

    "switch_track_on": "background-color: {success}; border-radius: 15px; border: none;",
    "switch_track_off": "background-color: {border}; border-radius: 15px; border: none;",
    "switch_knob": "background-color: #FFFFFF; border-radius: 13px; border: none;",

    "value_label": "color: {text_secondary}; font-size: 14px;",

    # ---- Pages -----------------------------------------------------------
    "page_bg": "background-color: {bg_primary};",
    "scroll_area": "QScrollArea {{ background-color: {bg_primary}; border: none; }}",

    # ---- Settings --------------------------------------------------------
    "settings_list": """
        QListWidget {{
            background-color: {bg_secondary};
            color: {text_primary};
            border: none;
            border-radius: 8px;
            padding: 4px;
        }}
        QListWidget::item:selected {{
            background-color: {scrollbar_pressed};
            color: {text_inverse};
            border-radius: 6px;
        }}
    """,

    "mini_button": """
        QPushButton {{
            background-color: {bg_tertiary};
            border-radius: 8px;
            color: {text_primary};
            border: none;
            padding: 6px 12px;
            font-size: 13px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    "combo_dropdown": """
        QComboBox {{
            background-color: {bg_secondary};
            border: none;
            border-radius: 8px;
            color: {text_primary};
            padding: 8px 12px;
            font-size: 10.5pt;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {bg_secondary};
            border: 1px solid {divider};
            selection-background-color: {accent};
            selection-color: {text_inverse};
            border-radius: 8px;
            padding: 4px;
        }}
    """,

    # ---- PosterBoard -----------------------------------------------------
    "tab_bar": "background-color: {bg_primary}; border-top: 1px solid {border};",

    "tab_button_inactive": "color: {text_secondary}; background: transparent; border: none; font-weight: 600; font-size: 14px;",
    "tab_button_active": "color: {accent}; background: transparent; border: none; font-weight: 600; font-size: 14px;",

    "add_icon": "background-color: {bg_secondary}; border: 2px dashed {divider}; border-radius: 12px; color: {accent}; font-size: 28px; font-weight: 300;",

    "tendie_preview_btn": """
        QToolButton {{
            background-color: {bg_secondary};
            color: {accent};
            border: 1px solid {divider};
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 13px;
        }}
        QToolButton:hover {{ background-color: {surface_hover}; }}
    """,

    "tendie_delete_btn": """
        QToolButton {{
            background-color: {bg_secondary};
            color: {error};
            border: 1px solid {divider};
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 13px;
        }}
        QToolButton:hover {{ background-color: {error}; color: {text_inverse}; }}
    """,

    "template_preview": "background-color: {bg_secondary}; border: 1px solid {divider}; border-radius: 12px;",

    "reset_pb_button": """
        QPushButton {{
            background-color: {bg_tertiary};
            border-radius: 8px;
            color: {error};
            border: none;
            padding: 10px 16px;
            font-size: 14px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    "download_card_icon": "background-color: {accent}; border-radius: 10px; color: white; font-size: 20px;",

    "thumb_button": """
        QPushButton {{
            background-color: {bg_secondary};
            color: {accent};
            border-radius: 8px;
            border: none;
            padding: 8px 16px;
            font-size: 14px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    # ---- Home ------------------------------------------------------------
    "home_title": "font-size: 32px; font-weight: 700; color: {text_primary};",
    "home_subtitle": "color: {text_secondary}; font-size: 14px;",

    "home_combo": """
        QComboBox {{
            background-color: {bg_secondary};
            border: none;
            border-radius: 10px;
            color: {text_primary};
            padding: 10px 14px;
            font-size: 10.5pt;
        }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView {{
            background-color: {bg_secondary};
            selection-background-color: {accent};
            selection-color: {text_inverse};
            border: none;
        }}
    """,

    "home_icon_button": """
        QPushButton {{
            background-color: {bg_secondary};
            color: {text_primary};
            border-radius: 10px;
            border: none;
            font-size: 16px;
            padding: 10px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    "home_card_header": "background-color: {bg_secondary}; border-radius: 12px 12px 0 0;",
    "home_card_title": "font-size: 17px; font-weight: 600; color: {text_primary};",
    "home_card_subtitle": "color: {text_secondary}; font-size: 13px;",

    "process_status_green": "color: {success}; font-size: 14px; font-weight: 500;",
    "process_status_red": "color: {error}; font-size: 14px; font-weight: 500;",
    "process_status_blue": "color: {accent}; font-size: 14px; font-weight: 500;",

    # ---- Daemons ---------------------------------------------------------
    "safety_note": "color: {danger_text}; font-size: 12px; font-style: italic;",

    # ---- Wallpaper downloader ---------------------------------------------
    "wp_card": """
        QFrame {{
            background-color: {bg_secondary};
            border-radius: 12px;
            border: none;
        }}
        QFrame:hover {{ background-color: {surface_hover}; }}
    """,

    "wp_name": "color: {text_primary}; font-size: 13px; font-weight: 600;",
    "wp_author": "color: {text_secondary}; font-size: 11px;",
    "wp_preview_bg": "background-color: {bg_tertiary};",
    "wp_loading_bg": "background-color: {bg_tertiary};",
    "wp_loading_text": "color: {text_disabled}; font-size: 12px;",

    "dialog_progress_bar": """
        QProgressBar {{
            background-color: {bg_tertiary};
            border: none;
            border-radius: 4px;
            height: 8px;
        }}
        QProgressBar::chunk {{
            background-color: {accent};
            border-radius: 4px;
        }}
    """,

    # ---- About dialog ----------------------------------------------------
    "about_separator": "background-color: {divider};",
    "about_desc": "color: {text_secondary}; font-size: 14px;",
    "about_credit_title": "color: {text_secondary}; font-size: 13px; font-weight: 600;",
    "about_link": "color: {accent}; font-size: 14px; border: none; background: transparent;",
    "about_link_hover": "color: {accent_hover}; font-size: 14px; border: none; background: transparent;",

    # ---- Interface picker ------------------------------------------------
    "picker_frame": """
        QFrame {{
            background-color: {bg_secondary};
            border-radius: 12px;
            border: 2px solid transparent;
        }}
        QFrame:hover {{ border-color: {accent}; }}
    """,

    # ---- Classic chrome (device bar) -------------------------------------

    "classic_bordered_btn": """
        QToolButton {{
            background: none;
            border: 1px solid {divider};
            color: {text_primary};
        }}
        QToolButton:hover {{
            background-color: {surface_hover};
        }}
        QToolButton:pressed {{
            background-color: {surface_hover};
            color: {text_primary};
        }}
    """,

    # ---- Global (main window stylesheet) ---------------------------------
    "global": """
        QWidget {{ color: {text_primary}; background-color: transparent; spacing: 0px; }}
        QWidget:focus {{ outline: none; }}
        QWidget[cls=central] {{ background-color: {bg_primary}; border-radius: 0px; border: 1px solid {divider}; }}
        QLabel {{ font-size: 14px; }}
        QToolButton {{ background-color: {scrollbar}; border: none; color: {text_primary}; font-size: 14px; min-height: 35px; icon-size: 16px; padding-left: 10px; padding-right: 10px; border-radius: 8px; }}
        QToolButton[cls=sidebarBtn] {{ background-color: transparent; icon-size: 24px; }}
        QToolButton:pressed {{ background-color: {scrollbar_pressed}; color: {text_primary}; }}
        QToolButton:checked {{ background-color: {accent}; color: {text_inverse}; }}
        QCheckBox {{ spacing: 8px; font-size: 14px; }}
        QRadioButton {{ spacing: 8px; font-size: 14px; }}
        QLineEdit {{ border: none; background-color: transparent; color: {text_primary}; font-size: 14px; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; }}
        QScrollBar:horizontal {{ background: transparent; height: 8px; }}
        QScrollBar::handle {{ background: {scrollbar}; border-radius: 4px; }}
        QScrollBar::handle:pressed {{ background: {scrollbar_pressed}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ background: none; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        QSlider::groove:horizontal {{ background-color: {scrollbar}; height: 4px; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background-color: {scrollbar_pressed}; width: 8px; border-radius: 4px; }}
        QSlider::handle:horizontal:pressed {{ background-color: {accent}; }}
        QSlider::tick:horizontal {{ background-color: {scrollbar_pressed}; width: 1px; }}
    """,
}
