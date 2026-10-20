# Forge Implementation Plan - Backend API

## Overview
This document tracks all backend API implementation tasks for the Forge KamiLimu Learning System using FastAPI. The plan focuses exclusively on building robust REST APIs that will be consumed by a separate frontend application. The implementation starts with authentication and user management, which must be completed and tested end-to-end before proceeding to other features.

---

## Phase 1: Authentication & User Management (PRIORITY)

### 1.1 Backend - Authentication Infrastructure
- [x] **Task 1.1.1**: Set up FastAPI project structure
  - Initialize FastAPI application
  - Configure environment variables for secrets management
  - Set up CORS middleware for Next.js frontend

- [x] **Task 1.1.2**: Configure Supabase connection — plain PostgreSQL via SQLAlchemy + asyncpg (works with Supabase Postgres); no Supabase client needed
  - Install Supabase Python client
  - Set up database connection pool
  - Configure connection string and credentials

- [x] **Task 1.1.3**: Implement JWT authentication system
  - Create JWT token generation utilities (access & refresh tokens)
  - Implement token validation and verification middleware
  - Set token expiration policies (access: 1 hour, refresh: 7 days)
  - Create token blacklist/revocation mechanism

- [x] **Task 1.1.4**: Create password hashing utilities
  - Implement bcrypt password hashing
  - Create password validation (minimum requirements)
  - Add password comparison utility

### 1.2 Backend - User Authentication Endpoints
- [x] **Task 1.2.1**: Create user invitation endpoint (Admin only)
  - POST `/api/auth/invite` - send invitation email
  - Generate unique invitation token (7-day expiry)
  - Store invitation in database with pending state
  - Integration with email service (Resend)

- [x] **Task 1.2.2**: Create bulk invitation endpoint (Admin only)
  - POST `/api/auth/bulk-invite` - accept CSV upload
  - Parse CSV with user details and role assignments
  - Generate invitations for multiple users
  - Return success/failure report per user

- [x] **Task 1.2.3**: Create account activation endpoint
  - POST `/api/auth/activate` - accept invitation token + password
  - Validate invitation token (not expired, not used)
  - Hash and store password
  - Mark account as active
  - Return access and refresh tokens

- [x] **Task 1.2.4**: Create login endpoint
  - POST `/api/auth/login` - accept email + password
  - Validate credentials
  - Check account state (reject if suspended)
  - Return access and refresh tokens
  - Log login event

- [x] **Task 1.2.5**: Create token refresh endpoint
  - POST `/api/auth/refresh` - accept refresh token
  - Validate refresh token
  - Issue new access token
  - Optionally rotate refresh token

- [x] **Task 1.2.6**: Create logout endpoint
  - POST `/api/auth/logout` - invalidate tokens
  - Add tokens to blacklist
  - Clear any server-side session data

- [x] **Task 1.2.7**: Create password reset flow
  - POST `/api/auth/request-reset` - send reset email
  - POST `/api/auth/reset-password` - complete reset with token

### 1.3 Backend - User Management Endpoints
- [x] **Task 1.3.1**: Get current user profile
  - GET `/api/users/me` - return authenticated user details
  - Include roles and cohort assignments

- [x] **Task 1.3.2**: Update user profile
  - PATCH `/api/users/me` - update own profile
  - Validate allowed fields per role

- [x] **Task 1.3.3**: Admin user management endpoints
  - GET `/api/admin/users` - list all users (paginated)
  - GET `/api/admin/users/:id` - get user details
  - PATCH `/api/admin/users/:id` - update user (admin)
  - POST `/api/admin/users/:id/suspend` - suspend user
  - POST `/api/admin/users/:id/activate` - reactivate user

### 1.4 Database - Authentication Schema
- [x] **Task 1.4.1**: Create users table
  - id (UUID, primary key)
  - email (unique, not null)
  - password_hash (nullable until activated)
  - first_name, last_name
  - account_state (pending/active/suspended)
  - created_at, updated_at
  - last_login_at

- [x] **Task 1.4.2**: Create invitations table
  - id (UUID, primary key)
  - email (not null)
  - token (unique, indexed)
  - expires_at (timestamp)
  - used_at (nullable timestamp)
  - invited_by (user_id FK)
  - created_at

- [x] **Task 1.4.3**: Create user_roles table
  - id (UUID, primary key)
  - user_id (FK to users)
  - role (enum: mentee/peer_mentor_1:1/peer_mentor_ict/professional_mentor/committee/partner/alumni/admin)
  - cohort_id (FK to cohorts, nullable for admin)
  - assigned_at
  - assigned_by (user_id FK)

- [x] **Task 1.4.4**: Create token_blacklist table
  - id (UUID, primary key)
  - token_jti (JWT ID, indexed)
  - blacklisted_at (timestamp)
  - expires_at (timestamp for cleanup)

- [x] **Task 1.4.5**: Create audit_logs table
  - id (UUID, primary key)
  - user_id (FK to users, nullable)
  - action (string - login/logout/invite/suspend etc.)
  - resource_type (string)
  - resource_id (UUID)
  - metadata (JSONB)
  - ip_address
  - created_at

### 1.5 Database - Row Level Security (RLS)
- [x] **Task 1.5.1**: Enable RLS on all tables — enforced in the API layer instead of Postgres RLS (see README › API conventions)
  - users, invitations, user_roles, token_blacklist, audit_logs

- [x] **Task 1.5.2**: Create RLS policies for users table
  - Users can read their own record
  - Users can update their own profile fields
  - Admins can read/update all users

- [x] **Task 1.5.3**: Create RLS policies for user_roles table
  - Users can read their own roles
  - Admins can create/update/delete roles
  - Committee can read all roles in their cohort

- [x] **Task 1.5.4**: Create RLS policies for audit_logs
  - Users can read their own audit logs
  - Admins can read all audit logs

### 1.6 API Documentation & Validation
- [x] **Task 1.6.1**: Set up OpenAPI/Swagger documentation
  - Configure automatic API docs at `/docs`
  - Add detailed descriptions for all endpoints
  - Include request/response schemas
  - Add authentication requirements documentation

- [x] **Task 1.6.2**: Create Pydantic models for request validation
  - UserInviteRequest model
  - BulkInviteRequest model
  - AccountActivationRequest model
  - LoginRequest model
  - TokenRefreshRequest model
  - PasswordResetRequest models

- [x] **Task 1.6.3**: Create Pydantic models for response serialization
  - UserResponse model
  - TokenResponse model
  - InvitationResponse model
  - ErrorResponse model (standardized error format)
  - SuccessResponse model

### 1.7 Testing - Authentication End-to-End
- [x] **Task 1.9.1**: Backend unit tests
  - Test password hashing functions
  - Test JWT generation and validation
  - Test token expiration logic

- [x] **Task 1.9.2**: Backend integration tests
  - Test full invitation flow
  - Test login with valid/invalid credentials
  - Test account state validations
  - Test token refresh flow
  - Test logout and token blacklisting

- [ ] **Task 1.9.3**: Frontend unit tests — belongs to the frontend repository
  - Test authentication context
  - Test form validations
  - Test API client interceptors

- [x] **Task 1.9.4**: End-to-end tests
  - Test complete invitation → activation → login flow
  - Test role-based access control
  - Test bulk invitation flow
  - Test password reset flow
  - Test session expiration and refresh

- [x] **Task 1.9.5**: Security testing
  - Test SQL injection on auth endpoints
  - Test JWT tampering
  - Test password requirements
  - Test rate limiting on login endpoint
  - Test expired/invalid token handling

### 1.10 Deployment - Authentication System
- [x] **Task 1.8.1**: Set up environment variables
  - Production secrets (JWT secret, DB credentials)
  - Email service API keys
  - CORS configuration (allowed origins for frontend)

- [ ] **Task 1.8.2**: Configure email service (Resend) — templates done; domain/DNS setup and live delivery test pending
  - Set up domain and DNS records
  - Create email templates for invitations
  - Test email delivery

- [ ] **Task 1.8.3**: Deploy backend to VM with Docker — Dockerfile and Compose done; nginx and SSL pending
  - Create Dockerfile for FastAPI app
  - Set up Docker Compose
  - Configure reverse proxy (nginx)
  - Set up SSL certificates

- [ ] **Task 1.8.4**: Production smoke tests
  - Test all auth endpoints in production
  - Test email delivery
  - Monitor logs for errors
  - Test API documentation accessibility

---

## Phase 2: Core System Setup (Depends on Phase 1)

### 2.1 Database - Core Entities
- [x] **Task 2.1.1**: Create cohorts table
  - id, name, programme_type
  - start_date, end_date
  - kami_limu_month_boundaries (JSONB)
  - graduation_threshold (default 80%)
  - ict_tracks_offered (JSONB array)
  - status (draft/active/completed)

- [x] **Task 2.1.2**: Create cohort_enrollments table
  - Links users to cohorts with roles
  - id, user_id, cohort_id, role
  - peer_mentor_group_id (for peer mentor assignments)
  - ict_track (for mentees)
  - enrolled_at, enrolled_by

### 2.2 Backend - Cohort Management API
- [x] **Task 2.2.1**: Create Pydantic models
  - CohortCreateRequest, CohortUpdateRequest
  - CohortResponse, CohortDetailResponse
  - EnrollmentRequest, EnrollmentResponse

- [x] **Task 2.2.2**: Cohort CRUD endpoints
  - POST `/api/cohorts` - create cohort
  - GET `/api/cohorts` - list cohorts (with pagination)
  - GET `/api/cohorts/:id` - get cohort details
  - PATCH `/api/cohorts/:id` - update cohort
  - DELETE `/api/cohorts/:id` - soft delete cohort

- [x] **Task 2.2.3**: Cohort enrollment endpoints
  - POST `/api/cohorts/:id/enrollments` - enroll users
  - GET `/api/cohorts/:id/enrollments` - list enrollments (paginated)
  - PATCH `/api/cohorts/:id/enrollments/:enrollment_id` - update enrollment
  - DELETE `/api/cohorts/:id/enrollments/:enrollment_id` - remove enrollment

### 2.3 Database - Row Level Security
- [x] **Task 2.3.1**: RLS policies for cohorts table — enforced in the API layer
  - All authenticated users can read active cohorts
  - Only admins can create/update/delete cohorts

- [x] **Task 2.3.2**: RLS policies for cohort_enrollments — enforced in the API layer
  - Users can read their own enrollments
  - Committee can read all enrollments in their cohort
  - Admins can manage all enrollments

### 2.4 Testing - Cohort Management API
- [x] **Task 2.4.1**: Backend unit tests for cohort logic
- [x] **Task 2.4.2**: API endpoint tests with pytest
- [x] **Task 2.4.3**: Test RLS policies
- [x] **Task 2.4.4**: Test pagination and filtering
- [x] **Task 2.4.5**: Integration tests for enrollment workflows

---

## Phase 3: Session Management (Depends on Phase 2)

### 3.1 Database - Session Schema
- [x] **Task 3.1.1**: Create sessions table
  - All fields from PRD section 7.3
  - Link to cohort_id
  - title, description, kami_limu_month
  - date_time, duration, session_category
  - track, session_type, location
  - points, status

- [x] **Task 3.1.2**: Create session_mentors table
  - Links professional/peer mentors to sessions
  - session_id, user_id, mentor_role (lead/co-mentor)

- [x] **Task 3.1.3**: Create session_resources table
  - Google Drive links for session materials
  - session_id, resource_type, url, description

### 3.2 Backend - Session Management API
- [x] **Task 3.2.1**: Create Pydantic models
  - SessionCreateRequest, SessionUpdateRequest
  - SessionResponse, SessionDetailResponse
  - SessionRescheduleRequest

- [x] **Task 3.2.2**: Session CRUD endpoints
  - POST `/api/sessions` - create session
  - GET `/api/sessions` - list sessions (with filters by cohort, track, month)
  - GET `/api/sessions/:id` - get session details
  - PATCH `/api/sessions/:id` - update session
  - DELETE `/api/sessions/:id` - cancel session

- [x] **Task 3.2.3**: Session calendar endpoints
  - GET `/api/cohorts/:id/calendar` - get full session calendar
  - GET `/api/cohorts/:id/calendar/:month` - get calendar by KamiLimu month

- [x] **Task 3.2.4**: Session rescheduling logic
  - POST `/api/sessions/:id/reschedule` - reschedule with history tracking
  - Preserve original date/time
  - Reset attendance windows
  - Trigger notifications

- [x] **Task 3.2.5**: Automatic attendance window calculation
  - Service to calculate window open/close times based on session_category
  - Thursday: closes 24h after end
  - Saturday: closes 48h after end
  - PeerMentorship: custom deadline

### 3.3 Database - Row Level Security
- [x] **Task 3.3.1**: RLS policies for sessions table — enforced in the API layer
  - All enrolled users can read published sessions in their cohort
  - Only admins/committee can create/update sessions
  - Draft sessions only visible to admins/committee

- [x] **Task 3.3.2**: RLS policies for session_mentors — enforced in the API layer
  - Professional mentors can read their assigned sessions
  - Admins/committee can manage all assignments

### 3.4 Testing - Session Management API
- [x] **Task 3.4.1**: Backend tests for session logic
- [x] **Task 3.4.2**: Test attendance window calculations
- [x] **Task 3.4.3**: API endpoint tests
- [x] **Task 3.4.4**: Test rescheduling workflow
- [x] **Task 3.4.5**: Test filtering and pagination

---

## Phase 4: Attendance Engine (Depends on Phase 3)

### 4.1 Database - Attendance Schema
- [x] **Task 4.1.1**: Create attendance_records table
  - mentee_id, session_id
  - status (pending/attended/not_attended/missed/excused/disputed)
  - quality_rating, usefulness_rating, understanding_score
  - academic_application_score, career_application_score
  - feedback (text), personal_notes (text)
  - submitted_at, updated_at

- [x] **Task 4.1.2**: Create attendance_windows table
  - session_id, opens_at, closes_at
  - is_active (boolean)

- [x] **Task 4.1.3**: Create attendance_window_overrides table
  - attendance_window_id, mentee_id
  - new_closes_at, reason, granted_by

- [x] **Task 4.1.4**: Create override_requests table
  - mentee_id, session_id, reason
  - status (pending/approved/denied)
  - reviewed_by, reviewed_at, review_reason

### 4.2 Backend - Attendance Engine API
- [x] **Task 4.2.1**: Create Pydantic models
  - AttendanceSubmissionRequest
  - AttendanceResponse, AttendanceDetailResponse
  - OverrideRequestCreate, OverrideRequestResponse
  - OverrideReviewRequest

- [x] **Task 4.2.2**: Attendance submission endpoints
  - POST `/api/attendance` - submit attendance record
  - GET `/api/attendance/me` - get my attendance records (filtered)
  - GET `/api/attendance/:id` - get specific attendance record
  - PATCH `/api/attendance/:id` - update attendance (within window)

- [x] **Task 4.2.3**: Attendance window management
  - GET `/api/sessions/:id/attendance-window` - check window status
  - POST `/api/attendance-windows/:id/close` - manual close (admin only)
  - Background job to auto-close expired windows

- [x] **Task 4.2.4**: Override request workflow
  - POST `/api/attendance/override-requests` - submit override request
  - GET `/api/attendance/override-requests` - list requests (role-based)
  - PATCH `/api/attendance/override-requests/:id/approve` - approve (committee)
  - PATCH `/api/attendance/override-requests/:id/deny` - deny (committee)

- [x] **Task 4.2.5**: Peer mentor and committee views
  - GET `/api/cohorts/:id/attendance` - get cohort attendance (committee)
  - GET `/api/peer-mentors/me/attendance` - get group attendance (peer mentors)

### 4.3 Database - Row Level Security
- [x] **Task 4.3.1**: RLS policies for attendance_records — enforced in the API layer
  - Mentees can read/write their own records
  - Peer mentors can read their group's records
  - Committee can read all records in their cohort

- [x] **Task 4.3.2**: RLS policies for override_requests — enforced in the API layer
  - Mentees can create and read their own requests
  - Committee can read/update all requests

### 4.4 Testing - Attendance Engine API
- [x] **Task 4.4.1**: Backend tests for attendance logic
- [x] **Task 4.4.2**: Test window calculations by session type
- [x] **Task 4.4.3**: Test override workflow
- [x] **Task 4.4.4**: API endpoint tests
- [x] **Task 4.4.5**: Test automatic window closure

---

## Phase 5: Points & Graduation Engine (Depends on Phase 4)

### 5.1 Backend - Points Calculation Service
- [x] **Task 5.1.1**: Real-time points calculation service — computed on demand with SQL aggregation; no cache layer yet
  - Calculate total points from core sessions
  - Calculate total points from extra activities
  - Combined total
  - Cache calculations for performance

- [x] **Task 5.1.2**: Attendance rate calculation service
  - Per KamiLimu month
  - Per track
  - Per session type
  - Overall rate (core + extra)

- [x] **Task 5.1.3**: Graduation eligibility service
  - Real-time status (on track/warning/at risk)
  - Final graduation determination
  - Handle edge cases (cancelled sessions, mid-cohort joins)

### 5.2 Backend - Points & Graduation API
- [x] **Task 5.2.1**: Create Pydantic models
  - PointsBreakdownResponse
  - AttendanceRateResponse
  - GraduationStatusResponse

- [x] **Task 5.2.2**: Points endpoints
  - GET `/api/mentees/:id/points` - get points breakdown
  - GET `/api/mentees/:id/points/breakdown` - detailed breakdown

- [x] **Task 5.2.3**: Attendance rate endpoints
  - GET `/api/mentees/:id/attendance-rates` - all rates
  - GET `/api/mentees/:id/attendance-rates/monthly` - by month
  - GET `/api/mentees/:id/attendance-rates/track` - by track

- [x] **Task 5.2.4**: Graduation status endpoints
  - GET `/api/mentees/:id/graduation-status` - current status
  - GET `/api/cohorts/:id/graduation-report` - full cohort report

### 5.3 Testing - Points Engine API
- [x] **Task 5.3.1**: Backend unit tests for calculations
- [ ] **Task 5.3.2**: Validate against Cohort 9 reference data — needs the Cohort 9 reference data
- [x] **Task 5.3.3**: Test edge cases (cancelled sessions, rescheduling)
- [x] **Task 5.3.4**: API endpoint tests
- [ ] **Task 5.3.5**: Performance tests for calculation speed

---

## Phase 6: Extra Activities Module (Depends on Phase 5)

### 6.1 Database - Extra Activities Schema
- [x] **Task 6.1.1**: Create extra_activities table
  - type (academic/event/opportunity/consultation)
  - mentee_id, cohort_id
  - title, description, date
  - status (pending/approved/rejected)
  - points_awarded
  - Type-specific fields (JSONB):
    - Academic: course_name, related_sessions, kami_limu_pillar
    - Event: event_role, mode, learnings
    - Opportunity: organization, application_date, outcome_status
    - Consultation: mentor_id, consultation_date, outcome
  - reviewed_by, reviewed_at, review_reason

### 6.2 Backend - Extra Activities API
- [x] **Task 6.2.1**: Create Pydantic models
  - AcademicActivityRequest, ExternalEventRequest
  - OpportunityApplicationRequest, ConsultationSessionRequest
  - ExtraActivityResponse, ExtraActivityDetailResponse
  - ActivityReviewRequest

- [x] **Task 6.2.2**: Activity submission endpoints
  - POST `/api/extra-activities/academic` - submit academic activity
  - POST `/api/extra-activities/events` - submit external event
  - POST `/api/extra-activities/opportunities` - submit opportunity
  - POST `/api/extra-activities/consultations` - submit consultation
  - GET `/api/extra-activities/me` - get my activities
  - PATCH `/api/extra-activities/:id` - update activity

- [x] **Task 6.2.3**: Committee validation endpoints
  - GET `/api/extra-activities/pending` - validation queue (committee)
  - PATCH `/api/extra-activities/:id/approve` - approve activity
  - PATCH `/api/extra-activities/:id/reject` - reject activity

- [x] **Task 6.2.4**: Points attribution logic
  - Auto-award points on approval
  - Update mentee total points
  - Trigger recalculation of graduation status

### 6.3 Database - Row Level Security
- [x] **Task 6.3.1**: RLS policies for extra_activities — enforced in the API layer
  - Mentees can create and read their own activities
  - Committee can read/update all activities in their cohort
  - Peer mentors can read their group's activities

### 6.4 Testing - Extra Activities API
- [x] **Task 6.4.1**: Backend tests for activity types
- [x] **Task 6.4.2**: API endpoint tests
- [x] **Task 6.4.3**: Test validation workflow
- [x] **Task 6.4.4**: Test points attribution

---

## Phase 7: Dashboard Data APIs (Depends on Phases 4-6)

### 7.1 Mentee Dashboard API
- [x] **Task 7.1.1**: Overview endpoint
  - GET `/api/dashboard/mentee/overview` - overview panel data
  - Overall attendance rate with status indicator
  - Total points (earned vs available)
  - Graduation eligibility status
  - Next upcoming session

- [x] **Task 7.1.2**: Attendance breakdown endpoints
  - GET `/api/dashboard/mentee/attendance/monthly` - by KamiLimu month
  - GET `/api/dashboard/mentee/attendance/track` - by track
  - GET `/api/dashboard/mentee/attendance/history` - full session history

- [x] **Task 7.1.3**: Extra activities endpoint
  - GET `/api/dashboard/mentee/extra-activities` - activities log

### 7.2 Peer Mentor Dashboard API
- [x] **Task 7.2.1**: 1:1 Peer Mentor endpoints
  - GET `/api/dashboard/peer-mentor/group` - group overview
  - GET `/api/dashboard/peer-mentor/mentees/:id` - individual drill-down
  - GET `/api/dashboard/peer-mentor/at-risk` - at-risk mentees
  - POST `/api/peer-mentor/notes` - create private note
  - GET `/api/peer-mentor/notes/:mentee_id` - get notes for mentee

- [x] **Task 7.2.2**: ICT Peer Mentor endpoints
  - GET `/api/dashboard/ict-peer-mentor/track-overview` - track mentees
  - GET `/api/dashboard/ict-peer-mentor/sessions` - ICT sessions view
  - POST `/api/ict-peer-mentor/progress-notes` - technical progress notes

### 7.3 Professional Mentor Dashboard API
- [x] **Task 7.3.1**: My sessions endpoint
  - GET `/api/dashboard/professional-mentor/sessions` - assigned sessions

- [x] **Task 7.3.2**: Feedback aggregation endpoint
  - GET `/api/sessions/:id/feedback` - aggregated feedback
  - Anonymous mentee identifiers

- [x] **Task 7.3.3**: Resource management
  - PATCH `/api/sessions/:id/resources` - update resource links

### 7.4 Committee Dashboard API
- [x] **Task 7.4.1**: Cohort health endpoint
  - GET `/api/dashboard/committee/cohort-health` - programme-wide summary
  - Total mentees, on-track count, warning/at-risk counts
  - Overall cohort attendance rate

- [x] **Task 7.4.2**: Queues endpoints
  - GET `/api/dashboard/committee/override-queue` - pending overrides
  - GET `/api/dashboard/committee/activities-queue` - pending activities

- [x] **Task 7.4.3**: Analytics endpoints
  - GET `/api/dashboard/committee/analytics/attendance-trends`
  - GET `/api/dashboard/committee/analytics/track-performance`
  - GET `/api/dashboard/committee/analytics/session-quality`

### 7.5 Database - Dashboard-specific tables
- [x] **Task 7.5.1**: Create peer_mentor_notes table
  - peer_mentor_id, mentee_id, note_text
  - created_at, updated_at

- [x] **Task 7.5.2**: Create ict_progress_notes table
  - ict_peer_mentor_id, mentee_id, session_id
  - progress_note, created_at

### 7.6 Testing - Dashboard APIs
- [x] **Task 7.6.1**: Test role-based data scoping
- [x] **Task 7.6.2**: API endpoint tests for all dashboard routes
- [x] **Task 7.6.3**: Test data aggregation accuracy
- [ ] **Task 7.6.4**: Performance tests for dashboard queries

---

## Phase 8: Leaderboard & Competition Module

### 8.1 Database - Leaderboard & Competitions
- [x] **Task 8.1.1**: Create competitions table
  - cohort_id, name, description
  - competition_type (innovation/public_speaking/scholarship/professional)
  - start_date, end_date, status

- [x] **Task 8.1.2**: Create competition_rounds table
  - competition_id, round_number, round_name
  - round_date, status

- [x] **Task 8.1.3**: Create competition_entries table
  - competition_id, round_id
  - mentee_id or team_id
  - status, result, notes

### 8.2 Backend - Leaderboard API
- [x] **Task 8.2.1**: Real-time leaderboard calculation service
  - Six dimensions: core attendance, graduation rate, academic activities, events, opportunities, consultations
  - Efficient query optimization

- [x] **Task 8.2.2**: Create Pydantic models
  - LeaderboardResponse, LeaderboardEntryResponse
  - DimensionRankingResponse

- [x] **Task 8.2.3**: Leaderboard endpoints
  - GET `/api/cohorts/:id/leaderboard` - full leaderboard
  - GET `/api/cohorts/:id/leaderboard/:dimension` - single dimension
  - GET `/api/cohorts/:id/leaderboard/export` - CSV export
  - PATCH `/api/cohorts/:id/leaderboard/settings` - anonymity toggle

### 8.3 Backend - Competition Management API
- [x] **Task 8.3.1**: Create Pydantic models
  - CompetitionCreateRequest, CompetitionResponse
  - RoundCreateRequest, RoundResponse
  - EntryUpdateRequest, EntryResponse

- [x] **Task 8.3.2**: Competition CRUD endpoints
  - POST `/api/competitions` - create competition
  - GET `/api/competitions` - list competitions (by cohort)
  - PATCH `/api/competitions/:id` - update competition

- [x] **Task 8.3.3**: Round management endpoints
  - POST `/api/competitions/:id/rounds` - create round
  - PATCH `/api/rounds/:id` - update round

- [x] **Task 8.3.4**: Entry management endpoints
  - POST `/api/competitions/:id/entries` - create entries
  - PATCH `/api/entries/:id` - update entry status/result
  - GET `/api/mentees/:id/competition-status` - mentee's status

### 8.4 Database - Row Level Security
- [x] **Task 8.4.1**: RLS policies for competitions — enforced in the API layer
  - All enrolled users can read competitions in their cohort
  - Committee can create/update competitions

- [x] **Task 8.4.2**: RLS policies for entries — enforced in the API layer
  - Mentees can read their own entries
  - Peer mentors can read their group's entries
  - Committee can manage all entries

### 8.5 Testing - Leaderboard & Competitions API
- [x] **Task 8.5.1**: Test ranking calculations
- [x] **Task 8.5.2**: API endpoint tests
- [x] **Task 8.5.3**: Test competition workflows
- [ ] **Task 8.5.4**: Performance tests for leaderboard queries

---

## Phase 9: Skill Progress & Peer Mentorship

### 9.1 Database - Skill Tracking
- [x] **Task 9.1.1**: Create skill_ratings table
  - mentee_id, cohort_id
  - rating_point (early/mid/late programme)
  - skill_1_rating through skill_6_rating (1-5 scale)
  - rated_at

- [x] **Task 9.1.2**: Create peer_mentor_tasks table
  - peer_mentor_id, cohort_id
  - title, description
  - launch_date, deadline_date
  - resource_link (optional)

- [x] **Task 9.1.3**: Create task_submissions table
  - task_id, mentee_id
  - submission_status (pending/completed)
  - submitted_at, notes

### 9.2 Backend - Skill Progress API
- [x] **Task 9.2.1**: Create Pydantic models
  - SkillRatingRequest, SkillRatingResponse
  - SkillProgressResponse (three rating points)

- [x] **Task 9.2.2**: Skill rating endpoints
  - POST `/api/skill-ratings` - submit skill rating
  - GET `/api/mentees/:id/skill-progress` - get progress arc
  - GET `/api/skill-ratings/windows` - check if rating window is open

### 9.3 Backend - Peer Mentorship API
- [x] **Task 9.3.1**: Create Pydantic models
  - PeerMentorTaskRequest, PeerMentorTaskResponse
  - TaskSubmissionRequest, TaskSubmissionResponse

- [x] **Task 9.3.2**: Task management endpoints
  - POST `/api/peer-mentor-tasks` - create task
  - GET `/api/peer-mentor-tasks` - list tasks (by peer mentor or mentee)
  - PATCH `/api/peer-mentor-tasks/:id` - update task

- [x] **Task 9.3.3**: Task submission endpoints
  - POST `/api/peer-mentor-tasks/:id/submit` - submit completion
  - GET `/api/peer-mentor-tasks/:id/submissions` - view submissions

### 9.4 Database - Row Level Security
- [x] **Task 9.4.1**: RLS policies for skill_ratings — enforced in the API layer
  - Mentees can create/read their own ratings
  - Peer mentors can read their group's ratings
  - Committee can read all ratings

- [x] **Task 9.4.2**: RLS policies for peer_mentor_tasks — enforced in the API layer
  - Peer mentors can create/manage their own tasks
  - Assigned mentees can read tasks and submit
  - Committee can read all tasks

### 9.5 Testing - Skill Progress & Peer Mentorship API
- [x] **Task 9.5.1**: Backend tests for skill rating logic
- [x] **Task 9.5.2**: API endpoint tests
- [x] **Task 9.5.3**: Test peer mentorship workflows
- [x] **Task 9.5.4**: Test rating window validation

---

## Phase 10: Notifications System

### 10.1 Database - Notifications
- [x] **Task 10.1.1**: Create notifications table
  - id, user_id, notification_type
  - title, message, metadata (JSONB)
  - sent_at, read_at, email_sent
  - related_resource_type, related_resource_id

### 10.2 Backend - Notification Service
- [x] **Task 10.2.1**: Email service integration (Resend)
  - Configure Resend API client
  - Create base email sending service

- [x] **Task 10.2.2**: Email template system
  - Session published/rescheduled/cancelled
  - Attendance window opening/closing soon
  - Graduation warnings (85%, below 80%)
  - Override request submitted/approved/denied
  - Extra activity approved/rejected
  - Peer mentorship task launched/deadline reminder
  - Cohort onboarding invitation

- [x] **Task 10.2.3**: Event-driven notification triggers
  - Create event system (observers/listeners)
  - Hook into session, attendance, override, activity events
  - Queue notifications for batch sending

- [x] **Task 10.2.4**: Notification queue and retry logic
  - Background job processing
  - Failed email retry mechanism
  - Notification status tracking

### 10.3 Backend - Notification API
- [x] **Task 10.3.1**: Create Pydantic models
  - NotificationResponse, NotificationListResponse

- [x] **Task 10.3.2**: Notification endpoints
  - GET `/api/notifications/me` - get my notifications
  - PATCH `/api/notifications/:id/read` - mark as read
  - PATCH `/api/notifications/read-all` - mark all as read

- [x] **Task 10.3.3**: Admin notification endpoints
  - POST `/api/notifications/broadcast` - send broadcast message
  - GET `/api/notifications/failed` - view failed notifications

### 10.4 Testing - Notifications API
- [x] **Task 10.4.1**: Test all notification triggers
- [x] **Task 10.4.2**: Test email delivery (use test mode) — delivery is mocked in tests
- [x] **Task 10.4.3**: API endpoint tests
- [x] **Task 10.4.4**: Test queue and retry logic

---

## Phase 11: Analytics & Reporting

### 11.1 Database - Analytics
- [x] **Task 11.1.1**: Create cohort_analytics_snapshots table
  - cohort_id, snapshot_date
  - metrics (JSONB: attendance trends, track performance, etc.)
  - created_at

### 11.2 Backend - Analytics Service
- [x] **Task 11.2.1**: Analytics calculation service
  - Attendance trends over programme months
  - Track performance comparison
  - Session quality rating trends
  - Monthly cohort health trajectory
  - Extra activities engagement by type

- [x] **Task 11.2.2**: Cross-cohort comparison service
  - Compare metrics across multiple cohorts
  - Historical trend analysis

- [x] **Task 11.2.3**: Export service
  - Generate CSV exports for reports
  - Leaderboard export
  - Attendance export
  - Full cohort report

### 11.3 Backend - Analytics API
- [x] **Task 11.3.1**: Create Pydantic models
  - AnalyticsResponse, TrendDataResponse
  - ExportRequestResponse

- [x] **Task 11.3.2**: Analytics endpoints
  - GET `/api/analytics/cohorts/:id/attendance-trends`
  - GET `/api/analytics/cohorts/:id/track-performance`
  - GET `/api/analytics/cohorts/:id/session-quality`
  - GET `/api/analytics/cohorts/:id/health-trajectory`
  - GET `/api/analytics/cross-cohort` - compare cohorts

- [x] **Task 11.3.3**: Export endpoints
  - POST `/api/exports/leaderboard/:cohort_id` - export leaderboard
  - POST `/api/exports/attendance/:cohort_id` - export attendance
  - POST `/api/exports/full-report/:cohort_id` - comprehensive report

### 11.4 Testing - Analytics API
- [x] **Task 11.4.1**: Validate calculation accuracy
- [x] **Task 11.4.2**: Test cross-cohort data queries
- [x] **Task 11.4.3**: API endpoint tests
- [x] **Task 11.4.4**: Test export generation

---

## Phase 12: Production Readiness

### 12.1 Performance Optimization
- [ ] **Task 12.1.1**: Database query optimization and indexing
- [ ] **Task 12.1.2**: API response caching
- [ ] **Task 12.1.3**: Frontend code splitting and lazy loading
- [ ] **Task 12.1.4**: Image and asset optimization
- [ ] **Task 12.1.5**: Load testing (target: 200 concurrent users)

### 12.2 Security Hardening
- [ ] **Task 12.2.1**: Security audit of all endpoints
- [x] **Task 12.2.2**: Rate limiting implementation
- [ ] **Task 12.2.3**: OWASP Top 10 vulnerability check
- [ ] **Task 12.2.4**: Penetration testing
- [x] **Task 12.2.5**: Data encryption at rest (for private notes)

### 12.3 Monitoring & Logging
- [x] **Task 12.3.1**: Application logging setup
- [ ] **Task 12.3.2**: Error tracking (Sentry or similar)
- [ ] **Task 12.3.3**: Performance monitoring (APM)
- [ ] **Task 12.3.4**: Database performance monitoring
- [ ] **Task 12.3.5**: Uptime monitoring and alerts

### 12.4 Backup & Recovery
- [ ] **Task 12.4.1**: Automated database backups
- [ ] **Task 12.4.2**: Backup restoration testing
- [ ] **Task 12.4.3**: Disaster recovery plan documentation
- [ ] **Task 12.4.4**: Data retention policy implementation

### 12.5 API Documentation
- [x] **Task 12.5.1**: Complete OpenAPI/Swagger documentation
  - Document all endpoints with examples
  - Include authentication requirements
  - Document all request/response schemas
  - Add error response examples

- [x] **Task 12.5.2**: Create API usage guide
  - Authentication flow documentation
  - Common use cases and examples
  - Rate limiting and pagination info

- [x] **Task 12.5.3**: Admin deployment guide
  - Server setup instructions
  - Docker deployment guide
  - Environment variable reference
  - Database migration guide

- [ ] **Task 12.5.4**: Troubleshooting guide
  - Common errors and solutions
  - Debugging tips
  - Log interpretation

- [ ] **Task 12.5.5**: Integration guide for frontend developers
  - API client setup examples
  - Authentication integration
  - WebSocket setup (if applicable)

### 12.6 User Acceptance Testing (UAT)
- [ ] **Task 12.6.1**: Backend API testing with committee
  - Test all critical user flows via API
  - Validate data accuracy

- [ ] **Task 12.6.2**: UAT with test cohort data
  - Import Cohort 9 historical data for validation
  - Verify calculations match reference data

- [ ] **Task 12.6.3**: Feedback collection and fixes
  - Document issues found
  - Prioritize and fix critical bugs

- [ ] **Task 12.6.4**: Final sign-off from committee
  - API completeness verification
  - Performance acceptance
  - Security review

### 12.7 Launch Preparation
- [ ] **Task 12.7.1**: Verify all Launch Readiness conditions (PRD Section 14)
  - Authentication system fully functional
  - All core APIs tested and documented
  - Database migrations ready
  - Email notifications working
  - RLS policies in place

- [ ] **Task 12.7.2**: Cohort 11 configuration in production
  - Create Cohort 11 via API
  - Configure session calendar
  - Set up KamiLimu month boundaries

- [ ] **Task 12.7.3**: Bulk import Cohort 11 users
  - Prepare CSV with user data
  - Execute bulk import
  - Verify user accounts created

- [ ] **Task 12.7.4**: Send invitation emails
  - Trigger invitation emails
  - Monitor email delivery

- [ ] **Task 12.7.5**: Monitor system during first week
  - Watch for errors and performance issues
  - Monitor email delivery rates
  - Track API usage and response times

- [ ] **Task 12.7.6**: Post-launch support and bug fixes
  - Quick response to critical issues
  - Daily monitoring for first week
  - Weekly check-ins for first month

---

## Dependency Map

```
Phase 1 (Auth) → Phase 2 (Core Setup) → Phase 3 (Sessions) → Phase 4 (Attendance)
                                                                      ↓
                                                                Phase 5 (Points)
                                                                      ↓
                                                                Phase 6 (Extra Activities)
                                                                      ↓
Phase 7 (Dashboards) depends on Phases 4, 5, 6
Phase 8 (Leaderboard) depends on Phase 5
Phase 9 (Skills/Peer Mentorship) depends on Phase 4
Phase 10 (Notifications) can run parallel with Phases 7-9
Phase 11 (Analytics) depends on all data collection phases
Phase 12 (Production) is final phase after all features complete
```

---

## Current Status

**Active Phase**: Phase 12 - Production Readiness
**Status**: Phases 1–11 implemented as a working API prototype (167 tests on real Postgres, 95% coverage)
**Blocker**: PRD business rules (points, thresholds, skills, KamiLimu months) use configurable defaults until confirmed
**Next Actions**: Validate rules against the PRD and Cohort 9 data, then performance tests, nginx/SSL deployment and production smoke tests

---

## Notes

- **Backend API Focus**: This implementation plan focuses exclusively on building FastAPI REST APIs. Frontend implementation is handled separately and will consume these APIs.
- **Testing Strategy**: Each phase must be fully tested (unit, integration, API endpoint tests) before moving to the next phase
- **Authentication First**: Phase 1 is the foundation - no work on other phases until auth is complete and tested end-to-end
- **RLS Implementation**: Row Level Security policies must be created alongside each database schema phase
- **API Documentation**: OpenAPI/Swagger docs should be updated continuously as endpoints are built
- **Reference Data**: Cohort 9 data from PRD Appendix should be used for validation testing
- **CORS Configuration**: Ensure proper CORS settings for frontend domain access

---

## Timeline Estimate

- **Phase 1**: 2-3 weeks (critical path - authentication and user management APIs)
- **Phase 2**: 1 week (cohort management APIs)
- **Phase 3**: 1-2 weeks (session management APIs)
- **Phase 4**: 2 weeks (attendance engine APIs)
- **Phase 5**: 1-2 weeks (points and graduation calculation APIs)
- **Phase 6**: 1 week (extra activities APIs)
- **Phase 7**: 2 weeks (dashboard data aggregation APIs)
- **Phase 8**: 1-2 weeks (leaderboard and competition APIs)
- **Phase 9**: 1 week (skill progress and peer mentorship APIs)
- **Phase 10**: 1-2 weeks (notifications system)
- **Phase 11**: 1 week (analytics and reporting APIs)
- **Phase 12**: 2-3 weeks (production readiness, testing, deployment)

**Total Estimated Time**: 16-22 weeks (~4-5.5 months)

Note: Timeline is shorter than original estimate since frontend implementation is excluded.

---

## Success Criteria

Each phase is considered complete when:
1. All tasks are checked off
2. Backend unit tests pass (>80% coverage)
3. Integration tests pass
4. API endpoint tests pass with all status codes validated
5. Pydantic models properly validate requests/responses
6. OpenAPI documentation updated
7. Code review completed
8. No critical or high-severity bugs
9. Performance metrics met (API response times < 2s for complex queries)

The backend API is ready for frontend integration and Cohort 11 launch when all conditions in PRD Section 14 are met.
