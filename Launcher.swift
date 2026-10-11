// Gives the local Python worker a stable macOS application identity for Bluetooth.
import AppKit

final class Launcher: NSObject, NSApplicationDelegate {
    var worker: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let defaultRoot = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/HueHorario")
        let root = (Bundle.main.object(forInfoDictionaryKey: "HueRuntimeDirectory") as? String)
            .map { URL(fileURLWithPath: $0) } ?? defaultRoot
        let command = CommandLine.arguments.dropFirst().first ?? "status"
        guard ["scan", "status", "on", "scheduled"].contains(command) else {
            exit(2)
        }
        let logURL = root.appendingPathComponent("app.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        do {
            let log = try FileHandle(forWritingTo: logURL)
            log.seekToEndOfFile()
            let process = Process()
            process.executableURL = root.appendingPathComponent(".venv/bin/python")
            process.arguments = [root.appendingPathComponent("hue.py").path, command,
                                 "--config", root.appendingPathComponent("config.json").path]
            process.standardOutput = log
            process.standardError = log
            process.terminationHandler = { child in
                let result: [String: Any] = [
                    "command": command, "exitCode": child.terminationStatus,
                    "finishedAt": ISO8601DateFormatter().string(from: Date())
                ]
                if let data = try? JSONSerialization.data(withJSONObject: result) {
                    try? data.write(to: root.appendingPathComponent("app-result.json"), options: .atomic)
                }
                DispatchQueue.main.async { NSApp.terminate(nil) }
            }
            worker = process
            try process.run()
        } catch {
            let message = "Launcher error: \(error)\n"
            try? message.write(to: root.appendingPathComponent("launcher-error.log"), atomically: true, encoding: .utf8)
            exit(1)
        }
    }
}

let app = NSApplication.shared
let delegate = Launcher()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
