use std::{
    cell::Cell,
    io,
    mem::size_of_val,
    os::windows::{
        io::{AsRawHandle, FromRawHandle, OwnedHandle},
        process::CommandExt,
    },
    process::{Child, Command},
    ptr::{null, null_mut},
};

use windows_sys::Win32::{
    Foundation::HWND,
    System::{
        JobObjects::{
            AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
            SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        },
        LibraryLoader::GetModuleHandleW,
        Threading::CREATE_NO_WINDOW,
    },
    UI::{
        Controls::LoadIconWithScaleDown,
        HiDpi::{GetDpiForWindow, GetSystemMetricsForDpi},
        Shell::ShellExecuteW,
        WindowsAndMessaging::{
            DestroyIcon, MessageBoxW, SendMessageW, HICON, ICON_BIG, ICON_SMALL, IDOK,
            MB_DEFBUTTON2, MB_ICONWARNING, MB_OKCANCEL, SM_CXSMICON, SM_CYSMICON, SW_SHOWNORMAL,
            WM_SETICON,
        },
    },
};

#[derive(Default)]
struct WindowIcon(Cell<usize>);

impl WindowIcon {
    fn load(&self, hwnd: HWND, kind: u32, width: i32, height: i32) {
        let mut icon: HICON = null_mut();
        let resource = tauri::utils::platform::WINDOWS_APP_ICON_RESOURCE_ID as usize as *const u16;
        let result = unsafe {
            LoadIconWithScaleDown(GetModuleHandleW(null()), resource, width, height, &mut icon)
        };
        if result < 0 || icon.is_null() {
            return;
        }
        unsafe { SendMessageW(hwnd, WM_SETICON, kind as usize, icon as isize) };
        // 只销毁本应用加载并替换掉的句柄。Tauri 的默认图标由 Tauri 管理。
        let previous = self.0.replace(icon as usize);
        if previous != 0 {
            unsafe { DestroyIcon(previous as HICON) };
        }
    }
}

impl Drop for WindowIcon {
    fn drop(&mut self) {
        let icon = self.0.get();
        if icon != 0 {
            unsafe { DestroyIcon(icon as HICON) };
        }
    }
}

pub fn install_dpi_icons(window: &tauri::WebviewWindow) {
    let Ok(hwnd) = window.hwnd() else {
        return;
    };
    let hwnd = hwnd.0 as usize;
    let caption = WindowIcon::default();
    let taskbar = WindowIcon::default();
    let update = move |dpi: u32| {
        let hwnd = hwnd as HWND;
        let (width, height) = unsafe {
            (
                GetSystemMetricsForDpi(SM_CXSMICON, dpi),
                GetSystemMetricsForDpi(SM_CYSMICON, dpi),
            )
        };
        caption.load(hwnd, ICON_SMALL, width, height);
        // 任务栏在 100% 缩放时使用 24 像素图标。200% 下直接加载 48 像素资源。
        let size = ((24 * dpi + 48) / 96) as i32;
        taskbar.load(hwnd, ICON_BIG, size, size);
    };
    let dpi = unsafe { GetDpiForWindow(hwnd as HWND) };
    if dpi != 0 {
        update(dpi);
    }
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::ScaleFactorChanged { scale_factor, .. } = event {
            update((96.0 * scale_factor).round() as u32);
        }
    });
}

pub fn confirm_exit(window: &tauri::Window) -> bool {
    let Ok(owner) = window.hwnd() else {
        return false;
    };
    let title: Vec<u16> = "退出 MoneyPrinterTurbo\0".encode_utf16().collect();
    let message: Vec<u16> = "确定要退出吗？退出会中断正在生成的视频。\0"
        .encode_utf16()
        .collect();
    // 取消是默认选项，避免在关闭窗口后误按回车退出。
    let choice = unsafe {
        MessageBoxW(
            owner.0,
            message.as_ptr(),
            title.as_ptr(),
            MB_OKCANCEL | MB_ICONWARNING | MB_DEFBUTTON2,
        )
    };
    choice == IDOK
}

pub fn hide_console(command: &mut Command) {
    command.creation_flags(CREATE_NO_WINDOW);
}

fn create_backend_job(process: &Child) -> io::Result<OwnedHandle> {
    // 由窗口持有 Job 句柄。退出或崩溃时，Windows 会回收 Python 及其子进程。
    let handle = unsafe { CreateJobObjectW(null(), null()) };
    if handle.is_null() {
        return Err(io::Error::last_os_error());
    }
    let job = unsafe { OwnedHandle::from_raw_handle(handle) };
    let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    let configured = unsafe {
        SetInformationJobObject(
            job.as_raw_handle(),
            JobObjectExtendedLimitInformation,
            (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
            size_of_val(&limits) as u32,
        )
    };
    if configured == 0 {
        return Err(io::Error::last_os_error());
    }
    if unsafe { AssignProcessToJobObject(job.as_raw_handle(), process.as_raw_handle()) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(job)
}

pub fn track_backend(mut process: Child) -> io::Result<(Child, OwnedHandle)> {
    match create_backend_job(&process) {
        Ok(job) => Ok((process, job)),
        Err(error) => {
            let _ = process.kill();
            let _ = process.wait();
            Err(error)
        }
    }
}

pub fn open_system_browser(url: &str) {
    let url: Vec<u16> = url.encode_utf16().chain(std::iter::once(0)).collect();
    unsafe {
        ShellExecuteW(
            null_mut(),
            null(),
            url.as_ptr(),
            null(),
            null(),
            SW_SHOWNORMAL,
        )
    };
}
