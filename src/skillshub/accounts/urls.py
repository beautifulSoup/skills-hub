from django.urls import path
from skillshub.accounts import views

urlpatterns = [
    path("", views.login_page, name="login"),
    path("request-otp", views.request_otp, name="request-otp"),
    path("verify", views.verify_otp, name="verify-otp"),
]
