$headers = @{ "Content-Type" = "application/json" }
$body = '{"email":"test_ps_signup_v4@example.com","password":"password123","first_name":"PS","last_name":"User","dob":"2000-01-01","role":"patient"}'
try {
    $response = Invoke-WebRequest -Uri "https://mediq-backend-m3ik.onrender.com/api/v1/auth/signup" -Method POST -Headers $headers -Body $body
    Write-Output "Status: $($response.StatusCode)"
    Write-Output "Content: $($response.Content)"
} catch {
    Write-Output "Error: $($_.Exception.Message)"
    if ($_.Exception.Response) {
         $stream = $_.Exception.Response.GetResponseStream()
         $reader = New-Object System.IO.StreamReader($stream)
         $respBody = $reader.ReadToEnd()
         Write-Output "Body: $respBody"
    }
}
