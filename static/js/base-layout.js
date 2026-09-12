/**
 * Travel Grant Management System - Base Layout JS
 * Handles navigation menu, mobile toggle, and layout interactions
 */

document.addEventListener('DOMContentLoaded', function () {
    // Initialize
    initNavigation();
    initMobileToggle();
    initDropdowns();
});

/**
 * Initialize Navigation Menu
 */
function initNavigation() {
    const navItems = document.querySelectorAll('.nxl-hasmenu > .nxl-link');

    navItems.forEach(link => {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            const parent = this.parentElement;
            toggleSubmenu(parent);
        });
    });
}

/**
 * Toggle Submenu Open/Close
 */
function toggleSubmenu(item) {
    // Close other open menus
    document.querySelectorAll('.nxl-hasmenu.open').forEach(openItem => {
        if (openItem !== item) {
            openItem.classList.remove('open');
        }
    });

    // Toggle current menu
    item.classList.toggle('open');
}

/**
 * Initialize Mobile Toggle
 */
function initMobileToggle() {
    const mobileToggler = document.getElementById('mobile-collapse');
    const navigation = document.querySelector('.nxl-navigation');

    if (mobileToggler) {
        mobileToggler.addEventListener('click', function (e) {
            e.preventDefault();
            navigation.classList.toggle('active');
        });
    }

    // Close menu when a link is clicked
    const navLinks = document.querySelectorAll('.nxl-link');
    navLinks.forEach(link => {
        link.addEventListener('click', function () {
            if (window.innerWidth <= 768) {
                navigation.classList.remove('active');
            }
        });
    });

    // Close menu on window resize
    window.addEventListener('resize', function () {
        if (window.innerWidth > 768) {
            navigation.classList.remove('active');
        }
    });
}

/**
 * Initialize Dropdowns
 */
function initDropdowns() {
    const dropdownToggles = document.querySelectorAll('[data-bs-toggle="dropdown"]');

    dropdownToggles.forEach(toggle => {
        toggle.addEventListener('click', function (e) {
            e.preventDefault();
            const dropdownMenu = this.nextElementSibling;

            if (dropdownMenu && dropdownMenu.classList.contains('dropdown-menu')) {
                // Close other dropdowns
                document.querySelectorAll('.dropdown-menu').forEach(menu => {
                    if (menu !== dropdownMenu) {
                        menu.classList.remove('show');
                    }
                });

                // Toggle current dropdown
                dropdownMenu.classList.toggle('show');
            }
        });
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', function (e) {
        const dropdownMenus = document.querySelectorAll('.dropdown-menu');
        dropdownMenus.forEach(menu => {
            if (!menu.parentElement.contains(e.target)) {
                menu.classList.remove('show');
            }
        });
    });
}

/**
 * Sidebar Mini/Expand Toggle (Menu Icon)
 */
function initSidebarToggle() {
    const miniButton = document.getElementById('menu-mini-button');
    const expendButton = document.getElementById('menu-expend-button');
    const navigation = document.querySelector('.nxl-navigation');

    if (miniButton) {
        miniButton.addEventListener('click', function (e) {
            e.preventDefault();
            navigation.classList.add('mini');
            miniButton.style.display = 'none';
            if (expendButton) expendButton.style.display = 'block';
        });
    }

    if (expendButton) {
        expendButton.addEventListener('click', function (e) {
            e.preventDefault();
            navigation.classList.remove('mini');
            expendButton.style.display = 'none';
            if (miniButton) miniButton.style.display = 'block';
        });
    }
}

/**
 * Active Menu Item
 */
function setActiveMenuItem(selector) {
    const links = document.querySelectorAll('.nxl-link');
    links.forEach(link => {
        link.classList.remove('active');
    });

    const activeLink = document.querySelector(selector);
    if (activeLink) {
        activeLink.classList.add('active');
        const parent = activeLink.closest('.nxl-item');
        if (parent && parent.classList.contains('nxl-hasmenu')) {
            parent.classList.add('open');
        }
    }
}

/**
 * Utility: Show Alert/Toast Message
 */
function showMessage(message, type = 'info', duration = 3000) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.setAttribute('role', 'alert');
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;

    const container = document.body;
    container.insertBefore(alertDiv, container.firstChild);

    if (duration > 0) {
        setTimeout(() => {
            alertDiv.remove();
        }, duration);
    }

    return alertDiv;
}

/**
 * Utility: Format Date
 */
function formatDate(date, format = 'YYYY-MM-DD') {
    if (typeof date === 'string') {
        date = new Date(date);
    }

    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');

    return format
        .replace('YYYY', year)
        .replace('MM', month)
        .replace('DD', day);
}

/**
 * Utility: Make API Call
 */
async function apiCall(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        }
    };

    const finalOptions = { ...defaultOptions, ...options };

    try {
        const response = await fetch(url, finalOptions);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('API call error:', error);
        throw error;
    }
}

/**
 * Utility: Get CSRF Token
 */
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === name + '=') {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

/**
 * Utility: Confirm Dialog
 */
function confirmDialog(message = 'Are you sure?') {
    return new Promise((resolve) => {
        if (confirm(message)) {
            resolve(true);
        } else {
            resolve(false);
        }
    });
}

// Export functions for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        initNavigation,
        toggleSubmenu,
        setActiveMenuItem,
        showMessage,
        formatDate,
        apiCall,
        getCookie,
        confirmDialog
    };
}
