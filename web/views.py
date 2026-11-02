from django.shortcuts import render


def index(request):
    return render(
        request,
        "web/index.html",
        {"start": request.GET.get("start", ""), "finish": request.GET.get("finish", "")},
    )
