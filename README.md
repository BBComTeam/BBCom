# BBCom

A modern, cross-platform serial communication tool built with Tauri and React.

![Version](https://img.shields.io/badge/version-1.1.7-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

## Features

### Serial Communication
- **Multiple Baud Rates** - Support for standard and custom baud rates (up to 4,000,000)
- **Configurable Serial Parameters** - Data bits, parity, stop bits, and flow control
- **Hardware Flow Control** - CTS, RTS, DTR pin configuration
- **Real-time RX/TX Monitoring** - Live data display with byte counters

### Log Management
- **Dual Display Modes** - ASCII and HEX formats
- **Timestamp & Direction Tags** - Optional [TX]/[RX] and timestamp prefixes
- **Syntax Highlighting** - Custom regex-based highlight rules (up to 10 rules)
- **Buffer Management** - Configurable log buffer (1,000 - 20,000 lines (can be up to 5,000,000))
- **Log Export** - Save logs to file for later analysis

### Command Panel
- **Command Presets** - Save and load command sets (JSONC format)
- **Quick Send** - One-click command execution
- **Loop Send** - Automated command sequencing with configurable delays
- **Drag & Drop Reordering** - Intuitive command organization

### User Experience
- **Custom Title Bar** - Modern frameless window design
- **Theme Support** - Dark, Light, and System themes with EVA-inspired colors
- **Multi-language** - English and Simplified Chinese (extensible)
- **Responsive Layout** - Resizable panels with drag handles
- **Configurable Fonts** - Customizable font family and size for log display

### Plus Features
- **More Highlight Actions** - Pause autoscroll when highlight hit, Bold.
- **Replay** - Load an existing log file and apply highlight and generate waveform view with BBCom.
- **Waveform** - values matches format "<var_name>=<var_value>;" can be displayed in waveform tab.
- **Terminal mode** - use BBCom as TCP/UDP terminal
  
## Screenshots

<img width="624" height="384" alt="bbcom_interface" src="https://github.com/user-attachments/assets/31821e20-250a-4f6a-bf51-03e468dfa3cb" />


## Installation

### Microsoft Store
Download BBCom from the Microsoft Store: https://apps.microsoft.com/detail/9ND3D780WC1W?hl=en-us&gl=CN&ocid=pdpshare.

## Configuration

BBCom stores user configurations in JSONC format, including:
- Serial port settings
- Display preferences
- Command sets
- Highlight rules
- Font settings

Configuration files can be saved, loaded, and shared between sessions.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter`  | Send data from input field |
| `Ctrl+L` | Toggle autoscroll |
| `Ctrl+G` | Toggle Connect / Disconnect |
| `Ctrl+P` | Toggle Pin (always on top) |
| `Ctrl+Wheel` | Adjust font size |

## Technology Stack

- **Frontend**: React 18, TypeScript, Zustand
- **Backend**: Tauri 2, Rust
- **UI Components**: Custom components with Lucide icons
- **Styling**: CSS with CSS Variables for theming
- **Internationalization**: i18next
- <span style="color: white; background-color: red; font-weight: bold;">PURELY Vibe-coded</span>

## Development

### Prerequisites
- Node.js 18+
- Rust 1.70+
- Windows 10/11

### Build Targets
- Windows: MSIX, NSIS installer


## Acknowledgments

- Built with [Tauri](https://tauri.app/)
- Icons by [Lucide](https://lucide.dev/)
- Inspired by classic serial terminal tools

---

**BBCom Team** © 2026
www.bbcom.online
