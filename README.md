# BBCom

A modern, cross-platform serial communication tool built with Tauri and React.

![Version](https://img.shields.io/badge/version-0.7.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
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
- **Buffer Management** - Configurable log buffer (1,000 - 20,000 lines)
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

## Screenshots

*Coming soon*

## Installation

### Microsoft Store
Download BBCom from the Microsoft Store (coming soon).

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
| `Ctrl+Enter` | Send data from input field |
| `Ctrl+L` | Clear log |
| `Ctrl+S` | Save configuration |
| `Ctrl+O` | Load configuration |
| `Ctrl+Wheel` | Adjust font size |

## Technology Stack

- **Frontend**: React 18, TypeScript, Zustand
- **Backend**: Tauri 2, Rust
- **UI Components**: Custom components with Lucide icons
- **Styling**: CSS with CSS Variables for theming
- **Internationalization**: i18next

## Development

### Prerequisites
- Node.js 18+
- Rust 1.70+
- Windows 10/11

### Build Targets
- Windows: MSIX, NSIS installer

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [Tauri](https://tauri.app/)
- Icons by [Lucide](https://lucide.dev/)
- Inspired by classic serial terminal tools

---

**BBCom Team** © 2026
www.bbcom.online
