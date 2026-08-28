![Artboard][NuggetLogo]

# GoldenNugget
Unlock your device's full potential, with iOS 27 support!

Customize your device with animated wallpapers, disable pesky daemons, and more!

Make sure you have installed the [requirements](#requirements) if you are on Windows or Linux.

> [!WARNING]
> Please back up your data before using this Project! GoldenNugget may cause unforeseen problems, so it is better to be safe than sorry. We are not responsible for any damage done to your device.

> [!NOTE]
> Make sure that you have enough free space on disk before applying tweaks.

> [!WARNING]
> This fork implements a three-phase backup→tweak→restore workflow to prevent data loss on iOS 27. Apple has patched the partial restore method that Nugget uses, so applying tweaks directly now triggers a security response that wipes AppleID, Keychain, Photos and settings. This fork preserves your data by backing it up first, then restoring it after the tweak is applied. **this fork is stable, but still do backup and I AM NOT RESPONSIBLE FOR ANY DATA LOSS/BOOTLOOP CAUSED BY GOLDENNUGGET.**

## Features
<details>
<summary>iOS 26.2 - 27.0+</summary>

- PosterBoard: Animated wallpapers and descriptors. (Does not support Apple's system descriptor, such as iOS 16 wallpaper)
  - Community wallpapers can be found [here][WallpapersWebsite]
  - Customizing community-made wallpapers via batter files
  - See documentation on the structure of tendies and batter files in [documentation.md](documentation.md)
- Templates: Custom Operations and file editing
  - See documentation on the structure of batter files in [documentation.md](documentation.md)
- psysbackup: backup system plist
  - Required to make "reset tweaks" function work without damaging system.
- Status Bar (disabled on iOS 27+, no write permissions for the Speakeasy feature flag)
  - Change carrier name
  - Change secondary carrier name
  - Enable/Disable the primary or secondary carriers
  - Change the number of WiFi/Cellular bars
  - Change the battery capacity
  - Change battery display detail
  - Change time text
  - Change date text (iPad only)
  - Change breadcrumb text
  - Show numeric WiFi/Cellular strength
  - Hide or show many icons in the status bar
- Springboard Options
  - Set Lock Screen Footnote
  - Set Lock Screen Idle Auto-Lock Time
  - Disable Lock After Respring
  - Disable Screen Dimming While Charging
  - Disable Low Battery Alerts
  - Hide AC Power on Lock Screen
  - Show Supervision Text on Lock Screen
  - Show Dynamic Island in Screenshots
  - Enable AirPlay support for Stage Manager
  - Show Red/Green Authentication Line on Lock Screen (See [this issue](https://github.com/leminlimez/Nugget/issues/656) for what it looks like)
  - Disable Floating Tab Bar on iPads
- Internal Options
  - ~~Enabling Key Flick (iPad-style keyboard) on iPhones~~ (removed — unsupported on iOS 26.2+)
  - Build Version in Status Bar
  - Force Right to Left
  - Show Hidden Icons on Home Screen
  - Force Metal HUD Debug
  - iMessage Diagnostics
  - IDS Diagnostics
  - VC Diagnostics
  - App Store Debug Gesture
  - Notes App Debug Mode
  - Show Touches With Debug Info
  - Hide Respring Icon
  - Play Sound on Paste
  - Show Notifications for System Pastes
- Disable Liquid Glass (iOS 26.0+):
  - Ignore Liquid Glass App Build Check (iOS 26.0+)
  - Force Solarium Fallback (iOS 26.0+, doesn't work on iOS 27 anymore)
- Disable Daemons:
  - OTAd
  - UsageTrackingAgent
  - Game Center
  - Screen Time Agent
  - Logs, Dumps, and Crash Reports
  - ATWAKEUP
  - Tipsd
  - VPN
  - Chinese WLAN service
  - HealthKit
  - AirPrint
  - Assistive Touch
  - iCloud
  - Internet Tethering (aka Personal Hotspot)
  - PassBook
  - Spotlight
  - Voice Control
</details>

## Contributors 

<div align="center">

**Thanks everyone who contributes to project!** 🎉

<a href="https://github.com/awesomenull-dev/GoldenNugget/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=awesomenull-dev/GoldenNugget" alt="Contributors" />
</a>

Want to see your name here? Open [Pull Request](https://github.com/awesomenull-dev/GoldenNugget/pulls)!

</div>

## Star History

<a href="https://www.star-history.com/?type=date&repos=awesomenull-dev%2FGoldenNugget">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=awesomenull-dev/GoldenNugget&type=date&theme=dark&legend=top-left&sealed_token=3Suw7Y0hFqwuBPijtmeM2A7pzK2ZCvEPoousYMJzOVFnPza-Aq5SzgNnEcgveIpQsBLEOL2QRtxwZbmaxn_S_3Lf9l0jINrMfRWkjFWGo3dVYCrFRpN6dA" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=awesomenull-dev/GoldenNugget&type=date&legend=top-left&sealed_token=3Suw7Y0hFqwuBPijtmeM2A7pzK2ZCvEPoousYMJzOVFnPza-Aq5SzgNnEcgveIpQsBLEOL2QRtxwZbmaxn_S_3Lf9l0jINrMfRWkjFWGo3dVYCrFRpN6dA" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=awesomenull-dev/GoldenNugget&type=date&legend=top-left&sealed_token=3Suw7Y0hFqwuBPijtmeM2A7pzK2ZCvEPoousYMJzOVFnPza-Aq5SzgNnEcgveIpQsBLEOL2QRtxwZbmaxn_S_3Lf9l0jINrMfRWkjFWGo3dVYCrFRpN6dA" />
 </picture>
</a>

<div align="center">
<br>We think you can star this repo if you think this is a good project.</br>
</div>

> [!NOTE]
> ## Mobilegestalt
> Don't even ask me for it. It will be NEVER realized again. 

## Requirements:
<details>
<summary>Windows</summary>
  
  - Either the [Apple Devices (from Microsoft Store)][AppleDevices] App or [iTunes (from Apple website)][iTunes]
</details>

<details>
<summary>Linux</summary>

  - [usbmuxd][usbmuxdGitHub]
  - [libimobiledevice][libimobiledeviceGitHub]
</details>

<details>
<summary>For Running Python</summary>

  - [pymobiledevice3][pymobiledevice3GitHub]
  - [PySide6][PySide6Doc]
  - Python 3.10 or newer
</details>

## Running the Python Program
> [!NOTE]
> It is highly recommended to use a virtual environment:
> ```py
> python3 -m venv .env # only needed once
> ```
macOS/Linux:
```py
source .env/bin/activate
```
Windows:
```py
.env/Scripts/activate.bat
```
Install Packages:
```py
pip3 install -r requirements.txt # only needed once
python3 main_app.py
```
> [!NOTE]
> Depending on your system configuration, use either `python/pip` or `python3/pip3`.

## Building
To compile `mainwindow.ui` for Python, run the following command:
```py
pyside6-uic --from-imports src/qt/mainwindow.ui -o src/qt/mainwindow_ui.py
```

To compile the resources file for Python, run the following command:
```py
pyside6-rcc src/qt/resources.qrc -o src/qt/resources_rc.py
```

To create and compile languages, you can use the following commands:
```py
pyside6-lupdate src/gui/main_window.py src/gui/pages/page.py src/gui/pages/pages_list.py src/gui/pages/main/*.py src/gui/pages/tools/*.py src/gui/dialogs/*.py src/gui/ios/*.py src/qt/mainwindow.ui src/devicemanagement/device_manager.py src/exceptions/*.py src/tweaks/*.py src/tweaks/posterboard/*.py src/tweaks/posterboard/template_options/*.py src/tweaks/status_bar/*.py src/controllers/*.py -ts src/qt/translations/Nugget_{language code}.ts # generate/update the language file
pyside6-lrelease src/qt/translations/Nugget_{language code}.ts -qm src/qt/translations/Nugget_{language code}.qm # compile to binary
```

The application itself can be compiled by running `compile.py`.

# Contributing and forking.
See [CONTRIBUTING.md](https://github.com/awesomenull-dev/GoldenNugget/blob/main/CONTRIBUTING.md), want fork instead? Then see [FORKING.md](https://github.com/awesomenull-dev/GoldenNugget/blob/main/FORKING.md)

## Credits
- Translations crowdsourced using [gNugget-i18n repository][i18n]
- [LEGACY] Translations crowdsourced using [POEditor][POEditorJoin]. Thank you everyone who assisted in the translation effort!
- [LeminLimez] for creating Nugget.
- [Wind0ws11Aero] for IOS 27 Support
- [PosterRestore][PosterRestoreDiscord] for their help with PosterBoard
  - Special thanks to [dootskyre][dootskyreX], [Middo][MiddoX], [dulark][dularkGitHub], forcequitOS, and pingubow for their work on this. It would not have been possible without them!
  - Thanks to [Snoolie for aar handling][python-aar-stuffGitHub]!
  - Thanks to [SerStars][SerStarsX] for creating [the website][WallpapersWebsite]!
- [disfordottie][disfordottieX] for some global flag features
- [iTechExpert][iTechExpertTwitter] for various Springboard/Internal Options
- [Mikasa-san][Mikasa-sanGitHub] for [Quiet Daemon][QuietDaemonGitHub]
- [pymobiledevice3][pymobiledevice3GitHub] for restoring and device algorithms.
- [PySide6][PySide6Doc] for the GUI library.

## Discord server
Wanted support? join our [Discord Server][server].

[i18n]: https://github.com/awesomenull-dev/gNugget-i18n
[NuggetLogo]: https://github.com/awesomenull-dev/GoldenNugget/blob/main/src/qt/credits/small_nugget.png
[LeminLimez]: https://github.com/leminlimez
[CowabungaLite]: https://github.com/leminlimez/CowabungaLite
[WallpapersWebsite]: https://cowabun.ga/wallpapers
[AppleDevices]: https://apps.microsoft.com/detail/9np83lwlpz9k
[iTunes]: https://support.apple.com/en-us/106372
[usbmuxdGitHub]: https://github.com/libimobiledevice/usbmuxd
[libimobiledeviceGitHub]: https://github.com/libimobiledevice/libimobiledevice
[ShortcutsApp]: https://apps.apple.com/us/app/shortcuts/id915249334
[MobilegestaltShortcut]: https://www.icloud.com/shortcuts/66bd3c822a0145b98d46cd1c9077e6e5
[ReadMoreGist]: https://gist.github.com/leminlimez/c602c067349140fe979410ef69d39c28
[Wind0ws11Aero]: https://github.com/Wind0ws11Aero
[POEditorJoin]: https://poeditor.com/join/project/UTqpVSE2UD
[JJTechGitHub]: https://github.com/JJTech0130
[TrollStoreGitHub]: https://github.com/JJTech0130/TrollRestore
[PosterRestoreDiscord]: https://discord.gg/gWtzTVhMvh
[dootskyreX]: https://x.com/dootskyre
[MiddoX]: https://x.com/MWRevamped
[dularkGitHub]: https://github.com/dularkian
[SerStarsX]: https://x.com/SerStars_lol
[disfordottieX]: https://x.com/disfordottie
[Mikasa-sanGitHub]: https://github.com/Mikasa-san
[QuietDaemonGitHub]: https://github.com/Mikasa-san/QuietDaemon
[sneakyf1shyGitHub]: https://github.com/f1shy-dev
[lrdsnowGitHub]: https://github.com/Lrdsnow
[EUEnablerGitHub]: https://github.com/Lrdsnow/EUEnabler
[pymobiledevice3GitHub]: https://github.com/doronz88/pymobiledevice3
[PySide6Doc]: https://doc.qt.io/qtforpython-6/
[python-aar-stuffGitHub]: https://github.com/0xilis/python-aar-stuff
[AIEligibilityGist]: https://gist.github.com/f1shy-dev/23b4a78dc283edd30ae2b2e6429129b5
[bl_sbxGitHub]: https://github.com/khanhduytran0/bl_sbx/tree/main
[DuyGitHub]: https://github.com/khanhduytran0
[HuyTwitter]: https://x.com/Little_34306
[iTechExpertTwitter]: https://twitter.com/iTechExpert21
[server]: https://discord.gg/RwbtH7pW5e
