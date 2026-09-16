from .tweak_names import TweakID
from .tweak_classes import BasicPlistTweak, AdvancedPlistTweak, NullifyFileTweak
from .posterboard.posterboard_tweak import PosterboardTweak
from .posterboard.template_options.templates_tweak import TemplatesTweak
from .status_bar.status_bar_tweak import StatusBarTweak
from .icon_themes.icon_themes_tweak import IconThemesTweak
    
tweaks = {
    ## PosterBoard
    TweakID.PosterBoard: PosterboardTweak(),

    ## Templates
    TweakID.Templates: TemplatesTweak(),

    ## Status Bar
    TweakID.StatusBar: StatusBarTweak(),

    ## Icon Themes
    TweakID.IconThemes: IconThemesTweak(),

}