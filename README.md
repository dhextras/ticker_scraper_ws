# TickerScraper WebSocket Setup Guide

This guide will walk you through the setup and configuration of the WebSocket server for the TickerScraper project, which integrates with the TickerScraper tool available on GitHub.

- TickerScraper repository: [dhextras/ticker_scraper](https://github.com/dhextras/ticker_scraper)

## Prerequisites

Make sure you have the following installed:
- **Python** (preferably version 3.6 or higher)
- **pip** (Python package installer)
- **virtualenv** (to create isolated Python environments)
- **Node.js** (for JWT generation)

If you don't have Python and pip installed, you can install them using the following command:
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv nodejs
```

## Step 1: Setup the Virtual Environment

1. **Create the virtual environment:**
   ```bash
   python3 -m venv venv
   ```

2. **Activate the virtual environment:**
   ```bash
   source venv/bin/activate
   ```

## Step 2: Install Dependencies

Install the required Python packages using:
```bash
pip install -r requirements.txt
```

## Step 3: Generate JWT Secret

Generate a secure JWT secret key using Node.js:
```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

Copy the output and use it in your `.env` file.

## Step 4: Create a `.env` File

1. **Create a file named `.env` in the root directory (you can use `.env.example` as a template).**
2. **Add the following configuration:**
   ```
   WS_HOST=0.0.0.0
   WS_PORT=8080
   TCP_HOST=your_tcp_server_host
   TCP_PORT=3005
   TCP_USERNAME=username
   TCP_SECRET=your_secret_key
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=group_id
   JWT_SECRET=your_generated_jwt_secret_from_step_3
   ```
   Replace the placeholder values with your actual configuration details.

## Step 5: Create a `webinterface/config.js` File

1. **Create a file named `config.js` in the webinterface directory.**
2. **Add the following details:**
   ```javascript
   window.env = {
      WEBSOCKET_URL: "ws://<DOMAIN/IP>:8080", // Replace with your domain or IP address
   };
   window.config = {
      senders: {
         // Add all the senders here
      },
      targets: {
         // Add the websocket targets here
      }
   };
   ```

## Step 6: Running the Server

1. **Start the server with sudo privileges:**
   Navigate to the root directory of your project and run:
   ```bash
   sudo python3 server.py
   ```

2. **Verify the server is running:**
   The server should now be running and serving both the WebSocket server and the web interface. The web interface will be available on port 80.

## Step 7: Access the Web Interface

Open your web browser and go to `http://localhost` or `http://your-server-ip` to access the web interface with authentication.

## File Structure Overview

Here is the current project structure:
```plaintext
ticker_scraper_ws/
├── .git/                    # Git repository files
├── data/                    # Data storage directory
│   ├── ignore_list.json     # List of ignored items
│   ├── ignored_messages.json # Ignored messages data
│   └── websocket_messages.json # WebSocket messages log
├── utils/                   # Utility scripts
│   ├── __init__.py          # Makes the folder a package
│   ├── base_logger.py       # Logger setup with timestamp and colored output
│   ├── error_notifier.py    # Telegram error notification
│   ├── logger.py            # Central logging functions
│   └── telegram_sender.py   # Telegram message sender
├── webinterface/            # Web interface files
│   ├── app.js               # Main application JavaScript
│   ├── auth.js              # Authentication handling
│   ├── config.js            # Web interface configuration
│   └── index.html           # Main web interface
├── websocket.py             # WebSocket server script
├── server.py                # Main server script
├── .env                     # Environment variables (create from .env.example)
├── .env.example             # Environment variables template
├── .gitignore               # Git ignore file
├── requirements.txt         # Project dependencies
└── README.md                # This documentation
```

## Important Notes

- **Authentication**: The web interface now includes JWT-based authentication for secure access.
- **JWT Secret**: Always generate a new JWT secret for production environments using the provided Node.js command.
- **Port 80**: The server runs on port 80 by default, which requires sudo privileges.
- **Environment Variables**: Make sure to configure your `.env` file properly before running the server.
- **Data Persistence**: The application stores data in JSON files within the `data/` directory.

## Troubleshooting

- If you encounter permission errors, make sure you're running the server with `sudo`.
- Ensure all environment variables in `.env` are properly configured.
- Check that ports 80 and 8080 are not being used by other applications.
- Verify your JWT secret is properly generated and added to the `.env` file.
