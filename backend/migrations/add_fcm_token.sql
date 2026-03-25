-- Add FCM device token column to users table for push notifications
ALTER TABLE users ADD COLUMN fcm_token VARCHAR;
