<?php
// 1. Allow access from any origin (Prevents CORS errors)
header("Access-Control-Allow-Origin: *");
header("Content-Type: application/json");

// 2. Create an 'uploads' folder if it doesn't exist
$uploadDir = 'uploads/';
if (!is_dir($uploadDir)) {
    mkdir($uploadDir, 0777, true);
}

// 3. Check if a file was actually uploaded
if (!isset($_FILES['file'])) {
    http_response_code(400);
    echo json_encode(["error" => "No file uploaded"]);
    exit;
}

$file = $_FILES['file'];
$fileName = basename($file['name']);
$targetFilePath = $uploadDir . $fileName;
$fileType = pathinfo($targetFilePath, PATHINFO_EXTENSION);

// 4. Only allow PDF files
if (strtolower($fileType) != "pdf") {
    http_response_code(400);
    echo json_encode(["error" => "Only PDF files are allowed"]);
    exit;
}

// 5. Move the file from temporary storage to the 'uploads' folder
if (move_uploaded_file($file['tmp_name'], $targetFilePath)) {
    // SUCCESS! 
    // Note: Real conversion happens here. For now, we just simulate success.
    http_response_code(200);
    echo json_encode([
        "status" => "success",
        "message" => "File uploaded successfully",
        "download_url" => "download.php?file=" . urlencode($fileName)
    ]);
} else {
    // SERVER ERROR (Usually permission issues)
    http_response_code(500);
    echo json_encode(["error" => "Failed to move uploaded file. Check folder permissions."]);
}
?>