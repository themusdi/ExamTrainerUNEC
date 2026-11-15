"""Registry of all screens (imported lazily by the App)."""
from ui.dashboard import HomeScreen
from ui.exam_screen import ExamScreen
from ui.history_screen import HistoryScreen
from ui.library_screen import LibraryScreen
from ui.results_screen import ResultsScreen
from ui.revision_screen import BookmarksScreen, RevisionScreen
from ui.settings_screen import SettingsScreen
from ui.setup_screen import SetupScreen
from ui.stats_screen import StatsScreen

SCREENS = {'home': HomeScreen, 'setup': SetupScreen, 'exam': ExamScreen, 'results': ResultsScreen,
           'library': LibraryScreen, 'revision': RevisionScreen, 'bookmarks': BookmarksScreen,
           'history': HistoryScreen, 'stats': StatsScreen, 'settings': SettingsScreen}
