from setuptools import setup, find_packages

setup(
    name="derpi-bot-dashboard",
    version="1.0.0",
    description="Async Derpibooru -> Telegram autoposter with web dashboard, WS updates, RBAC",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "aiohttp>=3.9",
        "python-dotenv>=1.0",
        "aiogram>=3.23.0",
    ],
    entry_points={
        "console_scripts": [
            "derpi-bot=app.main:run",
            "derpi-bot-cli=app.cli:run",
        ]
    },
    python_requires=">=3.10",
)
