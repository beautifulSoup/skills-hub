from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from skillshub.accounts import services, throttle as throttle_mod
from skillshub.accounts.forms import EmailForm, OtpForm
from skillshub.accounts.whitelist import is_email_allowed


@require_http_methods(["GET"])
def login_page(request):
    if request.user.is_authenticated:
        return redirect("/")
    return render(request, "accounts/login.html", {"form": EmailForm()})


@require_http_methods(["POST"])
def request_otp(request):
    form = EmailForm(request.POST)
    if not form.is_valid():
        return render(request, "accounts/_login_error.html", {"error": "请输入有效的邮箱地址"})

    email = form.cleaned_data["email"].lower().strip()

    if not is_email_allowed(email):
        return render(request, "accounts/_login_error.html", {"error": "您的邮箱不在允许范围内"})

    throttled, remaining = throttle_mod.is_throttled(email)
    if throttled:
        return render(
            request,
            "accounts/_login_error.html",
            {"error": f"请稍后再试（剩余 {remaining} 秒）"},
        )

    services.generate_otp(email)
    return render(request, "accounts/_otp_form.html", {"form": OtpForm(initial={"email": email}), "email": email})


@require_http_methods(["POST"])
def verify_otp(request):
    form = OtpForm(request.POST)
    if not form.is_valid():
        return render(request, "accounts/_login_error.html", {"error": "请输入 6 位数字验证码"})

    email = form.cleaned_data["email"].lower().strip()
    code = form.cleaned_data["code"].strip()

    success, error_msg = services.verify_otp_code(email, code)
    if not success:
        return render(request, "accounts/_login_error.html", {"error": error_msg})

    user = services.login_or_create_user(email)
    login(request, user)
    response = render(request, "accounts/_login_error.html", {"error": ""})
    response["HX-Redirect"] = "/"
    return response


@require_http_methods(["POST"])
def logout_view(request):
    logout(request)
    return redirect("/login")
