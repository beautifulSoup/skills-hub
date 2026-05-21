from django import forms


class EmailForm(forms.Form):
    email = forms.EmailField(
        label="邮箱",
        widget=forms.EmailInput(attrs={"placeholder": "your@company.com", "autofocus": True}),
    )


class OtpForm(forms.Form):
    email = forms.CharField(widget=forms.HiddenInput())
    code = forms.CharField(
        label="验证码",
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"placeholder": "6 位数字", "autofocus": True, "inputmode": "numeric"}),
    )
