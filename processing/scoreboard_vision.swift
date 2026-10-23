// Independent, read-only OCR of prepared scoreboard crops on macOS.
import Foundation
import Vision

let manifest = URL(fileURLWithPath: CommandLine.arguments[1])
let paths = try JSONDecoder().decode([String].self, from: Data(contentsOf: manifest))
for path in paths {
    var result: [String: Any] = ["path": path]
    do {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        request.recognitionLanguages = ["en-US"]
        request.minimumTextHeight = 0.01
        try VNImageRequestHandler(url: URL(fileURLWithPath: path)).perform([request])
        result["tokens"] = (request.results ?? []).compactMap { observation -> [String: Any]? in
            guard let candidate = observation.topCandidates(1).first else { return nil }
            return ["text": candidate.string, "confidence": Double(candidate.confidence)]
        }
    } catch {
        result["error"] = String(describing: error)
        result["tokens"] = []
    }
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    print(String(decoding: data, as: UTF8.self))
}
