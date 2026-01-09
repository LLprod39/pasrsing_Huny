# Synergy LMS Parser

**Comprehensive Documentation for AI Assistants and Developers**

This file provides complete guidance for working with the Synergy LMS Parser codebase.

---

## 📋 Project Overview

**Synergy LMS Parser** is a Python-based web scraper and automation tool for the Synergy LMS (Learning Management System) platform at `https://lms.synergy.ru`.

### Purpose
- Automate extraction of course materials and metadata
- Download videos and PDF documents from courses
- Track learning progress and completion status
- Export structured data about courses and materials
- Simulate course material viewing

### Technology Stack
- **Python 3.7+**
- **Selenium WebDriver** - Browser automation
- **BeautifulSoup4** - HTML parsing
- **Requests** - HTTP downloads
- **ThreadPoolExecutor** - Concurrent processing
- **Chrome/Chromium** - Automated browser

## Core Architecture

### Main Components

- **test.py** - Optimized parser with `SynergyLMSOptimizedParser` class
  - Uses `ThreadPoolExecutor` for parallel material processing
  - Combines HTTP requests and Selenium for efficiency
  - Primary data structures: `MaterialInfo` and `CourseInfo` dataclasses

- **parser.py** - Extended parser with `SynergyLMSParser` class
  - Handles video materials with playback simulation
  - Processes courses in separate browser tabs
  - Includes iframe content extraction
  - Background video download using `download_and_watch_video()` function

- **config.py** - Centralized configuration
  - `ParserConfig`: main settings (timeouts, workers, paths)
  - `Credentials`: authentication data
  - `BrowserOptions`: Chrome configuration with media permissions

### Key Data Flow

1. Authentication → Navigate semesters/courses → Extract materials → Download (optional) → Export JSON
2. Materials are parsed hierarchically from `ul.sidebar` DOM structure
3. Video downloads run in background threads while main process continues
4. Session persistence via `chrome_sessions/` directory

### Authentication

- Credentials stored in `config.py` or hardcoded in parser classes
- Login flow: Navigate to base URL → Click login popup → Enter credentials → Verify user-name div
- Uses CSS selectors: `#popupLogin`, `#popupUsername`, `#popupPassword`, `#popupLoginBtn`

## Common Commands

### Running the Parsers

```bash
# Main optimized parser (interactive menu)
python test.py

# Extended parser with tab-based course processing
python parser.py
```

### Installing Dependencies

```bash
pip install -r requirements.txt
```

### Project Structure

```
pasrsing/
├── parser.py                  # Extended parser with full functionality
├── test.py                    # Optimized parser with interactive menu
├── config.py                  # Centralized configuration file
├── requirements.txt           # Python dependencies
├── CLAUDE.md                  # This documentation file
├── chrome_sessions/           # Browser session data (auto-created)
└── downloaded_materials/      # Downloaded course materials (auto-created)
```

**Note**: The project automatically creates necessary directories (`chrome_sessions/`, `downloaded_materials/`, `logs/`) on first run.

## Browser Configuration

Chrome is configured with extensive flags for automation and media handling:

- **Media permissions**: `--use-fake-ui-for-media-stream`, `--use-fake-device-for-media-stream`
- **Performance**: Image/CSS loading can be disabled via `DISABLE_IMAGES`/`DISABLE_CSS` in config
- **Session persistence**: User data stored in `chrome_sessions/` with different profiles (`main`, `enhanced_automation`, etc.)

## Parsing Strategy

### Material Extraction

Materials are extracted from hierarchical `ul.sidebar` structure:
- Recursive parsing via `parse_materials()` function
- Identifies sections (with nested `ul`) vs. leaf materials (with href)
- Blocked materials detected via `resourse_blocked` class
- Each material includes: name, URL, data-index, blocking status

### Video Handling

Video processing involves:
1. Find video players by `.video-js` selector
2. Click `.vjs-big-play-button` to trigger real video URL loading
3. Extract duration from `.vjs-duration-display`
4. Parse duration string (HH:MM:SS or MM:SS) to seconds via `_parse_duration_to_seconds()`
5. Submit download task to ThreadPoolExecutor
6. Background thread downloads video and optionally simulates watching (sleep for duration)

### PDF Extraction

PDFs are found by:
- Searching `<script>` tags for `var file_path = "*.pdf"` pattern
- Direct download via requests library with progress bar (tqdm)

## Parallel Processing

- ThreadPoolExecutor pool size configurable via `MAX_WORKERS` (default: 5)
- Each course can use dynamic thread count based on available materials (max 20)
- Video downloads run in background threads while main thread continues processing
- Task futures are tracked for completion status

## Data Export

Materials exported to JSON with structure:
```json
{
  "course_name": "...",
  "url": "...",
  "materials": [
    {
      "name": "...",
      "url": "...",
      "viewing_time": "...",
      "progress": "...",
      "is_blocked": false,
      "type": "...",
      "timestamp": "..."
    }
  ]
}
```

## File Organization

### Directory Structure

- **Downloaded materials**: `downloaded_materials/[course_name]/[material_name].[ext]`
  - Organized by course name
  - Video files: `.mp4`, `.webm`, etc.
  - PDF documents: `.pdf`

- **Logs**: `synergy_parser.log` (auto-created in project root)
  - Contains detailed execution logs with timestamps
  - Includes authentication, parsing, and error information

- **Chrome sessions**: `chrome_sessions/[profile_name]/`
  - Stores browser cookies and session data
  - Profiles: `main`, `enhanced_automation`, `web_automation_session`
  - Enables faster re-authentication

- **Exported data**: `materials_[CourseName].json` (created in project root)
  - Structured JSON with course materials metadata
  - Created when using export functionality

## Important Implementation Details

- **Selenium waits**: Default `WebDriverWait` is 20 seconds
- **Iframe handling**: Switch context with `driver.switch_to.frame()` / `default_content()`
- **Material confirmation**: After processing, confirm study via `#exitBtn` button
- **Filename sanitization**: Use `re.sub(r'[<>:"/\\|?*]', '_', name)` for safe filenames
- **Error handling**: Extensive try/except blocks with logging; page source saved to `error_page_source.html` on failures

## When Modifying Code

### Important Considerations

- **Credentials**: Hardcoded in multiple places (`config.py`, `parser.py`, `test.py`) - update all locations if changing
- **Chrome options**: Defined in `BrowserOptions.get_chrome_options()` in `config.py` - modify there for global changes
- **Timeout values**: Scattered across files - consider centralizing in `config.py` if adding new features
- **Dual implementations**: Both `parser.py` and `test.py` have similar but divergent implementations - changes may need duplication

### Security Notes

⚠️ **WARNING**: This codebase contains hardcoded credentials in plaintext.

**Best practices for production use**:
1. Move credentials to environment variables or `.env` file
2. Add `.env` to `.gitignore`
3. Use Python's `python-dotenv` library to load credentials
4. Never commit credentials to version control

Example secure implementation:
```python
# .env file (not committed)
LMS_USERNAME=your_email@mail.ru
LMS_PASSWORD=your_password

# In config.py
from dotenv import load_dotenv
import os

load_dotenv()

@dataclass
class Credentials:
    username: str = os.getenv('LMS_USERNAME')
    password: str = os.getenv('LMS_PASSWORD')
```

---

## 🚀 Usage Examples

### Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Update credentials** in `config.py`:
   ```python
   username: str = "your_email@mail.ru"
   password: str = "your_password"
   ```

3. **Run parser**:
   ```bash
   python test.py  # Interactive menu
   # or
   python parser.py  # Full automation
   ```

### Common Workflows

#### Extract all course materials
1. Run `python test.py`
2. Select option to get all semesters
3. Choose semester number
4. Select courses to process
5. Data exported to JSON files

#### Download specific course materials
1. Run `python parser.py`
2. Choose semester
3. Select specific courses by number (comma-separated)
4. Choose specific materials from each course
5. Materials downloaded to `downloaded_materials/[course_name]/`

#### Analyze course progress
- Use exported JSON files
- Contains viewing times, progress percentages, completion status
- Can be parsed programmatically or viewed in text editor

---

## 🔧 Troubleshooting

### Common Issues

**Authentication fails**
- Verify credentials in `config.py`
- Check if LMS website structure changed
- Look for CAPTCHA or 2FA requirements
- Review `synergy_parser.log` for error details

**ChromeDriver errors**
- Ensure Chrome browser is installed
- Update `webdriver-manager`: `pip install --upgrade webdriver-manager`
- Check Chrome version compatibility

**Video download failures**
- Verify video player loads correctly (remove headless mode temporarily)
- Check network connectivity
- Ensure sufficient disk space
- Review iframe handling in logs

**Performance issues**
- Reduce `MAX_WORKERS` in `config.py` (default: 5)
- Enable headless mode: `HEADLESS_MODE = True`
- Disable image loading: `DISABLE_IMAGES = True`

### Debug Mode

To see browser actions in real-time:
1. Open `config.py`
2. Set `HEADLESS_MODE = False`
3. Run parser - browser window will be visible

---

## 📊 Data Structures

### MaterialInfo (dataclass)
```python
@dataclass
class MaterialInfo:
    name: str                     # Material title
    url: Optional[str]            # Material URL
    viewing_time: Optional[str]   # Time spent viewing
    progress: Optional[str]       # Completion progress
    is_blocked: bool              # Access blocked?
    level: int                    # Hierarchy depth
    data_index: Optional[str]     # LMS internal index
    type: str                     # Material type (video, pdf, etc.)
    timestamp: Optional[str]      # Data extraction time
    completion_status: Optional[str]  # Completion status
```

### CourseInfo (dataclass)
```python
@dataclass
class CourseInfo:
    name: str                    # Course name
    url: str                     # Course URL
    control_type: str            # Assessment type (exam, test, etc.)
    status: str                  # Course status
    materials_count: int         # Total materials
    total_time: str              # Total duration
    completion_percentage: float # Completion %
```

---

## 🛠️ Development Guidelines

### Adding New Features

1. **New material type support**:
   - Add detection logic in `process_material()` method
   - Implement download handler similar to `download_pdf_from_url()`
   - Update `MaterialInfo` dataclass if needed

2. **New export format**:
   - Add method in parser class (e.g., `export_to_csv()`)
   - Follow existing `export_to_json()` pattern
   - Update `EXPORT_FORMAT` in config

3. **Additional authentication methods**:
   - Modify `login()` method in parser classes
   - Handle new selectors/flow in authentication
   - Test thoroughly with different account types

### Code Style

- Follow existing patterns and naming conventions
- Add comprehensive logging for new functionality
- Use try/except blocks with specific error handling
- Document complex logic with inline comments
- Update this CLAUDE.md file when adding major features

---

## 📝 License & Disclaimer

This project is intended for educational purposes and personal automation of your own learning process.

**Disclaimer**:
- Only use with your own LMS account
- Respect the platform's terms of service
- Do not use for unauthorized access or data scraping
- The authors are not responsible for misuse

---

**Version**: 2.1
**Last Updated**: 2025-01-14
**Maintained by**: Synergy LMS Parser Team
