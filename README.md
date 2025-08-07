# Live Lines Finder

A subscription-gated, multi-platform chatbot providing sports betting analysis. The core logic is platform-agnostic and designed to be easily extended to new messaging platforms.

## Features

- **Multi-Platform:** Supports Telegram iMessage, a mock command-line interface for testing, and can be extended to other platforms.
- **Subscription Gating:** Access is controlled by checking for an active user subscription against a specific product ID in the database.
- **Configurable Modes:** Run in `live` or `test` modes to connect to different backend services or configurations.
- **Decoupled Architecture:** The central chatbot logic is completely separate from the platform-specific messaging clients.

## Project Structure

Key files and directories in the project:

```
.
├── src
│   ├── chatbot/core.py         # Core chatbot logic & subscription decorator
│   ├── database/models.py      # SQLAlchemy database models (User, Product, Subscription)
│   ├── database/session.py     # Database session management and initialization
│   ├── analysis/               # folder containing the analysis engines that process and analyse odds data 
│   ├── messaging/              # Platform-specific messaging clients
│   │   ├── base.py             # Abstract base class for all clients
│   │   ├── mock_client/        # Mock CLI client for local testing
│   │   └── telegram/           # Telegram bot client
│   │   └── imessage/           # iMessage bot client
│   ├── config.py               # Environment variable configuration
│   └── run_chatbot.py          # Main entry point to run the application
├── .env.example                # Example environment variables
└── requirements.txt            # Python dependencies
```

## Setup and Installation

1.  **Clone the Repository**
    ```bash
    git clone <your-repo-url>
    cd live-lines-finder
    ```

2.  **Create a Virtual Environment**
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**
    Create a `.env` file in the project root.

    -   `DATABASE_URL`: The connection string for your database which stores user data. Defaults to a local SQLite database (`chatbot.db`) if not set.
        -   *Example for PostgreSQL:* `postgresql://user:pass@host:port/dbname`
    -   `TELEGRAM_BOT_TOKEN`: Required to run the Telegram platform.
    -   `OPENAI_API_KEY`: Required for the chatbot's NLP capabilities.
    -   `PRODUCT_ID_LIVE` / `PRODUCT_ID_TEST`: The stripe product IDs used for subscription checks in different modes.

## Running the Chatbot

The application is launched using `src/run_chatbot.py`, which handles database initialization and starts the selected messaging client.

**Command-Line Arguments:**

-   `--platform`: Choose the messaging client.
    -   `mock`: An interactive command-line interface for testing.
    -   `telegram`: The live Telegram bot.
    -   `imessage`: The live iMessage bot
-   `--mode`: Set the operating mode.
    -   `test`: Uses test configurations (e.g., `PRODUCT_ID_TEST`).
    -   `live`: Uses live, production-ready configurations.
-   `--chat_id` (Optional): Specify a `chat_id` when using the `mock` platform to simulate messages from a specific user.

### Examples

**Run the Mock CLI for a specific user:**
```bash
python src/run_chatbot.py --platform mock --chat_id '+1234567890'
```

**Run the Bot in Live Mode:**
```bash
python src/run_chatbot.py --platform imessage --mode live
python src/run_chatbot.py --platform telegram --mode live
```
