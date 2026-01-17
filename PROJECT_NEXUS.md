# PROJECT NEXUS: MedIQ (MDQ+)

## 1. High-Level Context
* **Goal:** A Telehealth mobile app for finding doctors, booking video consultations, and AI symptom checking.
* **Tech Stack:** Flutter (Frontend), Riverpod (State), GoRouter (Nav), Python/FastAPI (Backend - Inferred), Agora (Video), Paystack (Payments).
* **Current Phase:** Polish & Feature Completion (Dark Mode, Profile Uploads, Notifications).

## 2. The "Brain Dump" (Active State)
* **Current Context:** We successfully implemented Dark Mode. We are currently blocked on **Profile Image Uploads**.
* **The Problem:** The frontend logic for picking images exists, but the backend communication (Repository/Controller) was inconsistent (using URLs vs Files).
* **Immediate Goal:** Fix the Profile Image upload pipeline (UI -> Controller -> Repo -> API) using `MultipartFile`.

## 3. Active Task List
- [ ] **Task 1 (Critical):** Fix Profile Image Upload (Full Stack: UI + Repo + Model).
- [ ] **Task 2:** specific "Upcoming Visit" card logic on Dashboard (currently static).
- [ ] **Task 3:** Implement Notifications Screen with local data.

## 4. Architecture Standards
* **Styling:** Custom Theme (Light/Dark support).
* **State Management:** Riverpod (AsyncNotifier/FutureProvider).
* **Rules:**
    * Do not use partial code snippets; provide full files.
    * Models must match API responses exactly (`imageUrl` vs `profile_image`).
    * Use `Dio` for all HTTP requests.

## 5. Shadow Log
* [2026-01-17]: Switched to Vehtracore Vibe Coding Blueprint to resolve context fragmentation.
* [2026-01-17]: Implemented AI Voice Chat (Web/Mobile).