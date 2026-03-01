$headers = @{ "Content-Type" = "application/json" }
$body = '{"emails": ["jennynlongs@gmail.com", "vickysylvester467@gmail.com"]}'

Write-Output "Deleting test users..."
try {
    $r = Invoke-WebRequest -Uri "https://mediq-backend-m3ik.onrender.com/api/v1/admin/delete-test-users" -Method POST -Headers $headers -Body $body
    Write-Output "Status: $($r.StatusCode)"
    Write-Output "Content: $($r.Content)"
} catch {
    Write-Output "Error: $($_.Exception.Message)"
}
