-- Clear random/placeholder health tip images.
-- Health tips should only show an image when admin uploaded/provided a real one.

UPDATE health_tips
SET image_url = NULL
WHERE image_url IS NOT NULL
  AND (
    LOWER(image_url) LIKE '%source.unsplash.com%'
    OR LOWER(image_url) LIKE '%images.unsplash.com%'
    OR LOWER(image_url) LIKE '%unsplash.com%'
    OR LOWER(image_url) LIKE '%picsum.photos%'
    OR LOWER(image_url) LIKE '%loremflickr.com%'
    OR LOWER(image_url) LIKE '%placehold.co%'
    OR LOWER(image_url) LIKE '%placeholder%'
    OR LOWER(image_url) LIKE '%dummyimage.com%'
    OR LOWER(image_url) LIKE '%placekitten.com%'
    OR LOWER(image_url) LIKE '%placebear.com%'
    OR LOWER(image_url) LIKE '%fakeimg.pl%'
  );
