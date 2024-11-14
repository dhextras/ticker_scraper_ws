# TickerScraper WebSocket Setup Guide

This guide will walk you through the setup and configuration of the WebSocket server for the TickerScraper project, which integrates with the TickerScraper tool available on GitHub.

- TickerScraper repository: [dhextras/ticker_scraper](https://github.com/dhextras/ticker_scraper)

## Prerequisites

Make sure you have the following installed:

- **Python** (preferably version 3.6 or higher)
- **pip** (Python package installer)
- **virtualenv** (to create isolated Python environments)

If you don't have Python and pip installed, you can install them using the following command:

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
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

## Step 3: Create a `webinterface/config.js` File

1. **Create a file named `config.js` webinterface directory.**
2. **Add the following details:**

   ```javascript
   window.env = {
      WEBSOCKET_URL: "ws://<DOMAIN/IP>:8080", // Replace your domain or Ip address
   }
   ```

## Step 4: Running the WebSocket Server

1. **Start the WebSocket server:**

   Navigate to the root directory of your project and run the following command:

   ```bash
   python websocket.py
   ```

2. **Verify the server is running:**

   The WebSocket server should now be running and ready to handle incoming connections. You can use WebSocket client tools (like browser extensions or other tools) to test the connection.

## Step 5: Hosting the Web Interface

1. **Host the `index.html` file on port 80:**

   To serve the web interface located in the `webinterface/` directory on port 80, you can use a simple HTTP server:

   ```bash
   sudo python3 -m http.server 80 --directory webinterface/
   ```

2. **Access the web interface:**

   Open your web browser and go to `http://localhost` to see the web interface.

## File Structure Overview

Here is a quick overview of the project structure:

```plaintext
ticker_scraper_ws/
├── data/                    # Folder for storing data files
├── webinterface/            # Web interface files
│   ├── index.html           # Main web interface
├── websocket.py             # WebSocket server script
├── .gitignore               # Git ignore file
├── requirements.txt         # Project dependencies
└── README.md                # Project documentation
```

### Important Notes

- Ensure to create and activate the virtual environment before installing dependencies.
- The WebSocket server and web interface must be running simultaneously for the full functionality of the application.
