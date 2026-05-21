"""Skill 提交表单 (R-14)。

字段：name / description / readme / tags / content
type 隐藏（默认 skill），无 tools 字段。
"""
from django import forms

_INPUT_CLASS = (
    "w-full px-3 py-2 text-sm bg-base-100 border border-base-300 rounded-md "
    "focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary "
    "placeholder-base-content/30"
)
_TEXTAREA_CLASS = (
    "w-full px-3 py-2 text-sm bg-base-100 border border-base-300 rounded-md "
    "focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary "
    "font-mono placeholder-base-content/30"
)
_FILE_CLASS = (
    "w-full text-sm text-base-content "
    "file:mr-3 file:px-4 file:py-2 file:text-sm file:font-medium "
    "file:rounded-md file:border-0 file:bg-base-200 file:text-base-content "
    "hover:file:bg-base-300 file:cursor-pointer cursor-pointer"
)


class SubmitSkillForm(forms.Form):
    name = forms.SlugField(
        label="Skill 名称",
        min_length=3,
        max_length=50,
        help_text="小写字母、数字、短横线，如 code-reviewer-zh",
        widget=forms.TextInput(attrs={"class": _INPUT_CLASS}),
    )

    def __init__(self, *args, lock_name: str | None = None, **kwargs):
        """lock_name 非 None 时（"重新提交此 skill" 场景）：name 字段锁定为该值，
        前端 disabled + Django form 的 disabled 属性自动忽略提交值。"""
        super().__init__(*args, **kwargs)
        if lock_name:
            self.fields["name"].disabled = True
            self.fields["name"].initial = lock_name
            self.fields["name"].help_text = "重新提交沿用原 skill 名称，不能修改。"
            self.initial["name"] = lock_name
    description = forms.CharField(
        label="简介",
        max_length=200,
        widget=forms.TextInput(attrs={"class": _INPUT_CLASS}),
    )
    readme = forms.CharField(
        label="详细说明（Markdown）",
        widget=forms.Textarea(attrs={"rows": 8, "class": _TEXTAREA_CLASS}),
    )
    tags = forms.CharField(
        label="标签（逗号分隔，可选）",
        required=False,
        help_text="如 code-review,python",
        widget=forms.TextInput(attrs={"class": _INPUT_CLASS}),
    )
    content = forms.FileField(
        label="Skill zip 包",
        help_text="zip 文件，根目录需含 SKILL.md；大小 ≤ 20 MB",
        widget=forms.ClearableFileInput(attrs={"class": _FILE_CLASS}),
    )

    def clean_tags(self) -> list[str]:
        raw = self.cleaned_data.get("tags", "")
        if not raw:
            return []
        # 同时兼容中文全角逗号 ，
        raw = raw.replace("，", ",")
        return [t.strip() for t in raw.split(",") if t.strip()]

    def clean_content(self):
        content = self.cleaned_data.get("content")
        if content and content.size > 20 * 1024 * 1024:
            raise forms.ValidationError("zip 文件大小不能超过 20 MB。")
        return content
