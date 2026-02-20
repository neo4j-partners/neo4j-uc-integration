# Docs

## Converting Excalidraw Diagrams

The `scripts/convert-excalidraw.js` script converts `.excalidraw` files in the `images/` directory to SVG and PNG formats using Puppeteer and the Excalidraw library.

### Prerequisites

Install Puppeteer:

```bash
npm install --save-dev puppeteer
```

### Usage

1. Place `.excalidraw` files in `site/images/`.
2. From the `site/` directory, run:

```bash
node scripts/convert-excalidraw.js
```

The script will generate `.svg` and `.png` files alongside each `.excalidraw` file in `site/images/`.
