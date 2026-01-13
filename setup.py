"""Setup script для установки synergy_lms в режиме разработки."""

from setuptools import setup, find_packages

setup(
    name="synergy-lms",
    version="2.0.0",
    description="Автоматизация просмотра материалов и прохождения тестов в LMS Synergy",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "selenium>=4.15.0",
        "webdriver-manager>=4.0.0",
        "python-dotenv>=1.0.0",
        "requests>=2.31.0",
        "beautifulsoup4>=4.12.0",
        "lxml>=4.9.0",
        "colorlog>=6.8.0",
        "textual>=0.58.0",
        "rich>=13.7.0",
        "google-genai>=0.2.0",
        "fastapi>=0.100.0",
        "uvicorn>=0.23.0",
    ],
)
