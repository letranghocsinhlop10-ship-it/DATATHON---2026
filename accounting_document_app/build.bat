@echo off
REM Dong goi ung dung thanh file chay Windows (.exe) bang PyInstaller.
REM Chay tu thu muc goc cua accounting_document_app, tren may Windows co
REM Python 3.12 da cai dat thu vien trong requirements.txt.
REM
REM Ket qua: dist\AccountingDocumentTool\AccountingDocumentTool.exe
REM (che do onedir - xem ghi chu trong accounting_app.spec ve ly do KHONG
REM dung --onefile: database SQLite va file log can mot vi tri co dinh de
REM ton tai qua nhieu lan chay, --onefile giai nen ra thu muc tam moi moi
REM lan mo ung dung se lam mat du lieu).

setlocal

where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay "python" trong PATH. Cai Python 3.12 truoc.
    exit /b 1
)

echo [1/4] Cai thu vien ung dung...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [2/4] Cai PyInstaller...
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :error

echo [3/4] Xoa ket qua build cu (neu co)...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [4/4] Dong goi bang PyInstaller...
python -m PyInstaller accounting_app.spec --noconfirm
if errorlevel 1 goto :error

echo.
echo Hoan tat. File chay o: dist\AccountingDocumentTool\AccountingDocumentTool.exe
echo Copy CA THU MUC "dist\AccountingDocumentTool" den may dich - khong copy rieng file .exe.
exit /b 0

:error
echo.
echo [LOI] Dong goi that bai. Xem log ben tren.
exit /b 1
