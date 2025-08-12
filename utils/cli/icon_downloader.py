#!/usr/bin/env python3
"""
Military Icon Downloader
Downloads SVG military symbols from a milsymbol server using SIDC codes from YAML file.
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import yaml


def load_yaml_config(yaml_file):
    """Load the YAML configuration file."""
    try:
        with open(yaml_file, "r") as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        print(f"Error: YAML file '{yaml_file}' not found.")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")
        sys.exit(1)


def download_icon(base_url, sidc_code, output_dir, cot_type, label, timeout=10):
    """Download a single SVG icon using requests."""
    # Remove .svg extension from SIDC code for URL
    clean_sidc = sidc_code.replace(".svg", "")

    # Construct URL and output filename (keep .svg extension for saved file)
    url = f"{base_url}/{sidc_code}"
    output_file = os.path.join(output_dir, sidc_code)

    try:
        # Make HTTP request
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()  # Raises an HTTPError for bad responses

        # Check if response contains SVG content
        content_type = response.headers.get("content-type", "").lower()
        if "svg" not in content_type and "<svg" not in response.text[:100]:
            return {
                "success": False,
                "sidc": sidc_code,
                "cot_type": cot_type,
                "label": label,
                "error": "Response does not appear to be SVG content",
            }

        # Save the SVG file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(response.text)

        return {
            "success": True,
            "sidc": sidc_code,
            "cot_type": cot_type,
            "label": label,
            "size": len(response.text),
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "sidc": sidc_code,
            "cot_type": cot_type,
            "label": label,
            "error": str(e),
        }
    except IOError as e:
        return {
            "success": False,
            "sidc": sidc_code,
            "cot_type": cot_type,
            "label": label,
            "error": f"File write error: {str(e)}",
        }


def download_icons_parallel(base_url, symbols, output_dir, max_workers=5):
    """Download multiple icons in parallel."""
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks
        future_to_symbol = {
            executor.submit(
                download_icon,
                base_url,
                symbol.get("sidc"),
                output_dir,
                symbol.get("cot_type", "Unknown"),
                symbol.get("label", "Unknown"),
            ): symbol
            for symbol in symbols
            if symbol.get("sidc")
        }

        # Process completed tasks
        for future in as_completed(future_to_symbol):
            result = future.result()
            results.append(result)

            if result["success"]:
                print(
                    f"✓ {result['label']} ({result['cot_type']}) - {result['size']} bytes"
                )
            else:
                print(f"✗ {result['label']} ({result['cot_type']}) - {result['error']}")

    return results


def download_icons_sequential(base_url, symbols, output_dir):
    """Download icons one by one (fallback method)."""
    results = []

    for i, symbol in enumerate(symbols, 1):
        sidc_code = symbol.get("sidc")
        cot_type = symbol.get("cot_type", "Unknown")
        label = symbol.get("label", "Unknown")

        if not sidc_code:
            print(f"Warning: No SIDC code found for symbol: {symbol}")
            continue

        print(f"[{i}/{len(symbols)}] Downloading {label} ({cot_type})")

        result = download_icon(base_url, sidc_code, output_dir, cot_type, label)
        results.append(result)

        if result["success"]:
            print(f"  ✓ Downloaded successfully - {result['size']} bytes")
        else:
            print(f"  ✗ Download failed: {result['error']}")

        # Small delay to be nice to the server
        time.sleep(0.1)

    return results


def test_server_connection(base_url):
    """Test if the milsymbol server is accessible."""
    test_url = f"{base_url}/SFGPU------.svg"  # Test with a basic friendly unit

    try:
        response = requests.get(test_url, timeout=5)
        response.raise_for_status()

        if "<svg" in response.text[:100]:
            print(f"✓ Server connection successful")
            return True
        else:
            print(f"✗ Server responded but content doesn't appear to be SVG")
            return False

    except requests.exceptions.RequestException as e:
        print(f"✗ Server connection failed: {e}")
        return False


def generate_html_report(symbols, results, output_dir, base_url):
    """Generate an HTML report showing all military symbols."""
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Military Symbols Reference</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background-color: #2c3e50;
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        .stats {{
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .stat-card {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            min-width: 150px;
        }}
        .stat-number {{
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
        }}
        .stat-label {{
            color: #666;
            font-size: 14px;
        }}
        .symbols-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
        }}
        .symbol-card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }}
        .symbol-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }}
        .symbol-card.failed {{
            border-left: 4px solid #e74c3c;
        }}
        .symbol-card.success {{
            border-left: 4px solid #27ae60;
        }}
        .symbol-icon {{
            text-align: center;
            margin-bottom: 15px;
        }}
        .symbol-icon svg {{
            max-width: 64px;
            max-height: 64px;
        }}
        .symbol-icon .error-icon {{
            width: 64px;
            height: 64px;
            background-color: #e74c3c;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 24px;
        }}
        .symbol-title {{
            font-size: 18px;
            font-weight: bold;
            color: #2c3e50;
            margin-bottom: 5px;
        }}
        .symbol-description {{
            color: #666;
            margin-bottom: 10px;
            font-size: 14px;
        }}
        .symbol-details {{
            font-size: 12px;
            color: #888;
        }}
        .symbol-details div {{
            margin-bottom: 3px;
        }}
        .category-friendly {{ background-color: #e8f5e8; }}
        .category-hostile {{ background-color: #ffe8e8; }}
        .category-neutral {{ background-color: #fff8e8; }}
        .category-unknown {{ background-color: #f0f0f0; }}
        .error-message {{
            color: #e74c3c;
            font-size: 12px;
            margin-top: 10px;
            padding: 8px;
            background-color: #fdf2f2;
            border-radius: 4px;
        }}
        .filter-bar {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .filter-buttons {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .filter-btn {{
            padding: 8px 16px;
            border: 1px solid #ddd;
            background: white;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .filter-btn:hover {{
            background-color: #f8f9fa;
        }}
        .filter-btn.active {{
            background-color: #007bff;
            color: white;
            border-color: #007bff;
        }}
        .search-box {{
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            margin-right: 10px;
            min-width: 200px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Military Symbols Reference</h1>
        <p>Generated from SIDC codes using MIL-STD-2525C standard</p>
        <p>Server: {base_url}</p>
    </div>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-number">{len(symbols)}</div>
            <div class="stat-label">Total Symbols</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{sum(1 for r in results if r['success'])}</div>
            <div class="stat-label">Successfully Downloaded</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{len(results) - sum(1 for r in results if r['success'])}</div>
            <div class="stat-label">Failed Downloads</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{len(set(s.get('category', 'unknown') for s in symbols))}</div>
            <div class="stat-label">Categories</div>
        </div>
    </div>

    <div class="filter-bar">
        <input type="text" id="searchBox" class="search-box" placeholder="Search symbols...">
        <div class="filter-buttons">
            <button class="filter-btn active" onclick="filterByCategory('all')">All</button>
            <button class="filter-btn" onclick="filterByCategory('friendly')">Friendly</button>
            <button class="filter-btn" onclick="filterByCategory('hostile')">Hostile</button>
            <button class="filter-btn" onclick="filterByCategory('neutral')">Neutral</button>
            <button class="filter-btn" onclick="filterByCategory('unknown')">Unknown</button>
            <button class="filter-btn" onclick="filterByStatus('success')">Downloaded</button>
            <button class="filter-btn" onclick="filterByStatus('failed')">Failed</button>
        </div>
    </div>

    <div class="symbols-grid" id="symbolsGrid">
"""

    # Create a lookup for results
    result_lookup = {r["sidc"]: r for r in results}

    # Generate symbol cards
    for symbol in symbols:
        sidc = symbol.get("sidc", "")
        cot_type = symbol.get("cot_type", "Unknown")
        label = symbol.get("label", "Unknown")
        description = symbol.get("description", "No description")
        category = symbol.get("category", "unknown")

        result = result_lookup.get(sidc, {"success": False, "error": "Not processed"})
        status_class = "success" if result["success"] else "failed"

        # SVG content or error icon
        if result["success"]:
            svg_path = os.path.join(output_dir, sidc)
            if os.path.exists(svg_path):
                with open(svg_path, "r", encoding="utf-8") as f:
                    svg_content = f.read()
            else:
                svg_content = '<div class="error-icon">?</div>'
        else:
            svg_content = '<div class="error-icon">✗</div>'

        html_content += f"""
        <div class="symbol-card {status_class} category-{category}" data-category="{category}" data-status="{'success' if result['success'] else 'failed'}" data-search="{label.lower()} {description.lower()} {cot_type.lower()}">
            <div class="symbol-icon">
                {svg_content}
            </div>
            <div class="symbol-title">{label}</div>
            <div class="symbol-description">{description}</div>
            <div class="symbol-details">
                <div><strong>CoT Type:</strong> {cot_type}</div>
                <div><strong>SIDC:</strong> {sidc.replace('.svg', '')}</div>
                <div><strong>Category:</strong> {category.title()}</div>
                <div><strong>Status:</strong> {'✓ Downloaded' if result['success'] else '✗ Failed'}</div>
            </div>
            {f'<div class="error-message"><strong>Error:</strong> {result["error"]}</div>' if not result['success'] else ''}
        </div>
        """

    html_content += """
    </div>

    <script>
        let currentFilter = 'all';
        let currentStatus = 'all';

        function filterByCategory(category) {
            currentFilter = category;
            applyFilters();

            // Update button states
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
        }

        function filterByStatus(status) {
            currentStatus = status;
            applyFilters();

            // Update button states
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
        }

        function applyFilters() {
            const searchTerm = document.getElementById('searchBox').value.toLowerCase();
            const cards = document.querySelectorAll('.symbol-card');

            cards.forEach(card => {
                const category = card.dataset.category;
                const status = card.dataset.status;
                const searchContent = card.dataset.search;

                const matchesCategory = currentFilter === 'all' || category === currentFilter;
                const matchesStatus = currentStatus === 'all' || status === currentStatus;
                const matchesSearch = searchTerm === '' || searchContent.includes(searchTerm);

                if (matchesCategory && matchesStatus && matchesSearch) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
        }

        // Search functionality
        document.getElementById('searchBox').addEventListener('input', applyFilters);

        // Reset filters when clicking "All"
        document.addEventListener('DOMContentLoaded', function() {
            const allBtn = document.querySelector('.filter-btn');
            allBtn.addEventListener('click', function() {
                currentFilter = 'all';
                currentStatus = 'all';
            });
        });
    </script>
</body>
</html>
"""

    # Save HTML file
    html_file = os.path.join(output_dir, "military_symbols_reference.html")
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    return html_file


def main():
    """Main function to download all military icons."""
    # Configuration
    BASE_URL = "http://localhost:2525"
    YAML_FILE = "config/settings/cot.yaml"  # Change this to your YAML file name
    OUTPUT_DIR = "static/cot_icons"
    PARALLEL = True  # Set to False for sequential downloads
    MAX_WORKERS = 5  # Number of parallel downloads
    GENERATE_HTML = True  # Set to False to skip HTML generation

    # Parse command line arguments
    if len(sys.argv) > 1:
        YAML_FILE = sys.argv[1]
    if len(sys.argv) > 2:
        OUTPUT_DIR = sys.argv[2]
    if len(sys.argv) > 3:
        BASE_URL = sys.argv[3]

    print(f"Military Icon Downloader")
    print(f"========================")
    print(f"YAML File: {YAML_FILE}")
    print(f"Output Directory: {OUTPUT_DIR}")
    print(f"Base URL: {BASE_URL}")
    print(f"Mode: {'Parallel' if PARALLEL else 'Sequential'}")
    print(f"Generate HTML: {'Yes' if GENERATE_HTML else 'No'}")
    print()

    # Test server connection
    print("Testing server connection...")
    if not test_server_connection(BASE_URL):
        print(
            "Cannot connect to server. Please check the URL and ensure the server is running."
        )
        sys.exit(1)
    print()

    # Load YAML configuration
    config = load_yaml_config(YAML_FILE)

    if "military_symbols" not in config:
        print("Error: 'military_symbols' key not found in YAML file.")
        sys.exit(1)

    # Create output directory
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    # Download icons
    symbols = config["military_symbols"]
    total_symbols = len(symbols)

    print(f"Found {total_symbols} symbols to download...")
    print()

    start_time = time.time()

    if PARALLEL:
        results = download_icons_parallel(BASE_URL, symbols, OUTPUT_DIR, MAX_WORKERS)
    else:
        results = download_icons_sequential(BASE_URL, symbols, OUTPUT_DIR)

    end_time = time.time()

    # Calculate results
    successful_downloads = sum(1 for r in results if r["success"])
    failed_downloads = len(results) - successful_downloads

    # Summary
    print()
    print(f"Download Summary:")
    print(f"================")
    print(f"Total symbols: {total_symbols}")
    print(f"Successful downloads: {successful_downloads}")
    print(f"Failed downloads: {failed_downloads}")
    print(f"Download time: {end_time - start_time:.2f} seconds")
    print(f"Icons saved to: {OUTPUT_DIR}")

    # Show failed downloads
    if failed_downloads > 0:
        print("\nFailed Downloads:")
        for result in results:
            if not result["success"]:
                print(f"  - {result['label']}: {result['error']}")

    # Generate HTML report
    if GENERATE_HTML:
        print("\nGenerating HTML report...")
        html_file = generate_html_report(symbols, results, OUTPUT_DIR, BASE_URL)
        print(f"HTML report saved to: {html_file}")
        print(f"Open in browser: file://{os.path.abspath(html_file)}")


if __name__ == "__main__":
    main()
