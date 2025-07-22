# live-lines-finder
Live arbitrage and mispriced lines identifier

## Bot Setup and Configuration

This section details how to set up and configure the Telegram bot associated with this project.

### Database Configuration

The application uses SQLAlchemy to connect to a database for storing user information, primarily their `chat_id` and `phone_number`.

-   **Default Behavior:** By default, if no specific configuration is provided, the application will use a local SQLite database. A file named `telegram_users.db` will be automatically created in the project's root directory when the bot first needs to access the database.
-   **Using PostgreSQL (Recommended for Production):** For more robust and scalable deployments (e.g., using services like Supabase, Heroku Postgres, or any other PostgreSQL instance), you can configure the bot to use a PostgreSQL database.
    -   To do this, you must set the `DATABASE_URL` environment variable.
    -   The format for the `DATABASE_URL` is `postgresql://username:password@host:port/database_name`.
    -   **Example:** `DATABASE_URL=postgresql://user:strongpassword@db.example.com:5432/mydatabase`
-   **Database Driver:** Ensure you have the necessary database driver installed. For PostgreSQL, this is `psycopg2-binary`, which is included in the `requirements.txt` file.

### Running the Telegram Bot

The core logic for the Telegram bot resides in `src/messaging/telegram/bot.py`.

1.  **Set Environment Variables:**
    *   `TELEGRAM_BOT_TOKEN`: This is essential. You must obtain this token from BotFather on Telegram.
        Example: `TELEGRAM_BOT_TOKEN='123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'`
    *   `DATABASE_URL`: (Optional, see Database Configuration above). If not set, SQLite will be used.
    *   Other environment variables like `ODDS_API_KEY` might be needed for full application functionality but are not strictly required just to run the bot for user registration. These are typically defined in a `.env` file which is loaded by the application (see `src/config.py`).

2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Initialize the Database (if needed):**
    The bot will attempt to create database tables on startup if they don't exist (as defined in `src/database/session.py` via the `init_db()` function). For a new setup, this should happen automatically.

4.  **Run the Bot:**
    Execute the bot script from the project's root directory:
    ```bash
    python src/messaging/telegram/bot.py
    ```
    You should see log messages indicating that the bot is initializing and then polling for updates from Telegram.

### User Interaction Flow

The interaction between a user and the bot is designed to be simple and facilitate notifications:

1.  **Initiation (`/start` command):**
    -   A new user messages the bot and sends the `/start` command.
    -   The bot registers the user's unique `chat_id`.

2.  **Contact Sharing Prompt:**
    -   Upon receiving the `/start` command, the bot replies with a welcome message and prompts the user to share their contact information. This is done via a special Telegram button that requests contact sharing permission.

3.  **Storing Phone Number:**
    -   If the user accepts and shares their contact, the bot receives their phone number.
    -   This phone number is then stored in the database, associated with their `chat_id`.

4.  **Notification Eligibility:**
    -   Once a user has shared their contact (and thus has a phone number stored), they become eligible to receive notifications sent by the system.
    -   The `TelegramNotifier` component (in `src/notifier.py`) is responsible for sending messages. It queries the database for all users who have provided a phone number and sends the notification to their respective `chat_id`. Users who have not shared their contact will not receive these notifications.

This setup allows users to opt-in to notifications by providing their contact details, ensuring they consent to being messaged by the bot.
