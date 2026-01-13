from __future__ import annotations

from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.index, name="index"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("subscriptions/", views.subscriptions, name="subscriptions"),
    path("payments/", views.payments, name="payments"),
    path("plans/", views.plans, name="plans"),
    path("jobs/", views.jobs, name="jobs"),
    # Flow like CLI
    path("synergy/", views.synergy_setup, name="synergy_setup"),
    path("flow/semesters/", views.flow_semesters, name="flow_semesters"),
    path("flow/courses/", views.flow_courses, name="flow_courses"),
    path("flow/materials/", views.flow_materials, name="flow_materials"),
]
