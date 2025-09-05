#!/usr/bin/env python3

import asyncio
import datetime
import logging
import uuid
import xml.etree.ElementTree as ET
from threading import Thread

import pytak
from flask import Flask, flash, jsonify, render_template_string, request

# Set up logging
logging.basicConfig(level=logging.INFO)
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

app = Flask(__name__)
app.secret_key = "your-secret-key-here"

# HTML template embedded in the application
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TAK CoT Message Sender</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #555;
        }
        input[type="text"], input[type="number"], select {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 16px;
            box-sizing: border-box;
        }
        input[type="text"]:focus, input[type="number"]:focus, select:focus {
            outline: none;
            border-color: #007bff;
            box-shadow: 0 0 5px rgba(0,123,255,0.25);
        }
        button {
            background-color: #007bff;
            color: white;
            padding: 12px 30px;
            border: none;
            border-radius: 4px;
            font-size: 16px;
            cursor: pointer;
            width: 100%;
        }
        button:hover {
            background-color: #0056b3;
        }
        button:disabled {
            background-color: #6c757d;
            cursor: not-allowed;
        }
        .alert {
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 4px;
        }
        .alert-success {
            background-color: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .alert-error {
            background-color: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .coordinates-row {
            display: flex;
            gap: 15px;
        }
        .coordinates-row .form-group {
            flex: 1;
        }
        #status {
            margin-top: 20px;
            min-height: 20px;
        }
        .loading {
            display: none;
        }
        .loading.show {
            display: inline-block;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>TAK CoT Message Sender</h1>
        
        <form id="cotForm">
            <div class="form-group">
                <label for="tak_server">TAK Server IP:</label>
                <input type="text" id="tak_server" name="tak_server" value="127.0.0.1" required>
            </div>
            
            <div class="form-group">
                <label for="tak_port">TAK Server Port:</label>
                <input type="number" id="tak_port" name="tak_port" value="8087" required>
            </div>
            
            <div class="form-group">
                <label for="callsign">Callsign:</label>
                <input type="text" id="callsign" name="callsign" placeholder="e.g., ALPHA-1" required>
            </div>
            
            <div class="form-group">
                <label for="cot_type">CoT Type:</label>
                <input type="text" id="cot_type" name="cot_type" placeholder="e.g., a-f-G-U-C" required>
                <small style="color: #666; font-size: 12px; margin-top: 5px; display: block;">
                    Common types: a-f-G-U-C (Friendly Ground), a-h-G (Hostile), a-n-G (Neutral), b-m-p-w (Waypoint)
                </small>
            </div>
            
            <div class="coordinates-row">
                <div class="form-group">
                    <label for="latitude">Latitude:</label>
                    <input type="number" id="latitude" name="latitude" step="any" value="35.0" required>
                </div>
                <div class="form-group">
                    <label for="longitude">Longitude:</label>
                    <input type="number" id="longitude" name="longitude" step="any" value="-85.0" required>
                </div>
            </div>
            
            <button type="submit" id="submitBtn">
                Send CoT Message
                <span class="loading" id="loading">...</span>
            </button>
        </form>
        
        <div id="status"></div>
    </div>

    <script>
        document.getElementById('cotForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            const submitBtn = document.getElementById('submitBtn');
            const loading = document.getElementById('loading');
            const status = document.getElementById('status');
            
            // Show loading state
            submitBtn.disabled = true;
            loading.classList.add('show');
            status.innerHTML = '';
            
            fetch('/send_cot', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    status.innerHTML = '<div class="alert alert-success">' + data.message + '</div>';
                } else {
                    status.innerHTML = '<div class="alert alert-error">Error: ' + data.error + '</div>';
                }
            })
            .catch(error => {
                status.innerHTML = '<div class="alert alert-error">Network error: ' + error.message + '</div>';
            })
            .finally(() => {
                submitBtn.disabled = false;
                loading.classList.remove('show');
            });
        });
    </script>
</body>
</html>
"""


class CoTSender:
    def __init__(self):
        self.loop = None
        self.thread = None

    async def send_cot_message(self, server_ip, server_port, callsign, cot_type, lat, lon):
        """Send a CoT message to the TAK server"""
        try:
            # Create CoT message
            cot_xml = self.create_cot_message(callsign, cot_type, lat, lon)
            logger.info(f"Generated CoT XML: {cot_xml}")

            # Create a simple TCP connection and send raw CoT
            reader, writer = await asyncio.open_connection(server_ip, server_port)

            # Send the CoT message
            writer.write(cot_xml.encode("utf-8"))
            await writer.drain()

            # Close connection
            writer.close()
            await writer.wait_closed()

            return True, f"CoT message sent successfully to {server_ip}:{server_port}"

        except Exception as e:
            logger.error(f"Error sending CoT message: {str(e)}")
            return False, str(e)

    def create_cot_message(self, callsign, cot_type, lat, lon):
        """Create a CoT XML message"""
        # Generate unique ID using callsign format
        uid = f"{callsign}-{int(datetime.datetime.now().timestamp() * 1000000) % 1000000000000}"

        # Get current time using timezone-aware datetime
        now = datetime.datetime.now(datetime.UTC)
        time_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")  # Simplified format without microseconds

        # Calculate stale time (5 minutes from now to match your example)
        stale_time = now + datetime.timedelta(minutes=5)
        stale_str = stale_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Get formatted timestamp for remarks
        remarks_time = now.strftime("%m/%d/%Y %H:%M:%S UTC")

        # Create CoT XML matching your format
        cot_xml = f'<event version="2.0" uid="{uid}" type="{cot_type}" time="{time_str}" start="{time_str}" stale="{stale_str}" how="m-g"><point lat="{lat:.8f}" lon="{lon:.8f}" hae="0.00" ce="999999.00" le="999999.00"/><detail><contact callsign="{callsign}"/><remarks>Last Reported: {remarks_time}</remarks></detail></event>'

        return cot_xml


# Global CoT sender instance
cot_sender = CoTSender()


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/send_cot", methods=["POST"])
def send_cot():
    try:
        # Get form data
        server_ip = request.form.get("tak_server", "127.0.0.1")
        server_port = int(request.form.get("tak_port", 8087))
        callsign = request.form.get("callsign", "")
        cot_type = request.form.get("cot_type", "")
        # Safely parse latitude/longitude with NaN injection protection
        lat_str = request.form.get("latitude", "0.0")
        lng_str = request.form.get("longitude", "0.0")

        # Check for NaN injection attempts (case-insensitive)
        if lat_str.lower() in ["nan", "inf", "-inf", "+inf"]:
            lat_str = "0.0"
        if lng_str.lower() in ["nan", "inf", "-inf", "+inf"]:
            lng_str = "0.0"

        # Use try/except with explicit validation to prevent NaN injection
        try:
            latitude = float(lat_str)
            if not (-90.0 <= latitude <= 90.0):
                latitude = 0.0
        except (ValueError, TypeError):
            latitude = 0.0

        try:
            longitude = float(lng_str)
            if not (-180.0 <= longitude <= 180.0):
                longitude = 0.0
        except (ValueError, TypeError):
            longitude = 0.0

        # Validate required fields
        if not callsign or not cot_type:
            return jsonify({"success": False, "error": "Callsign and CoT Type are required"})

        # Run async function in thread
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    cot_sender.send_cot_message(
                        server_ip, server_port, callsign, cot_type, latitude, longitude
                    )
                )
            finally:
                loop.close()

        # Execute in thread to avoid blocking Flask
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_async)
            success, message = future.result(timeout=30)  # 30 second timeout

        return jsonify({"success": success, "message" if success else "error": message})

    except Exception as e:
        logger.error(f"Error in send_cot route: {str(e)}")
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    print("Starting TAK CoT Sender Web Interface...")
    print("Open your browser to http://localhost:5000")
    print("Make sure you have pytak installed: pip install pytak")
    app.run(debug=True, host="0.0.0.0", port=8000)
