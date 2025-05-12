<?php
/**
 * Plugin Name: Elementor Custom Password Page
 * Description: Override WordPress password-protected pages with a custom Elementor-designed form.
 * Version: 3.2
 * Author: You
 */
if (!defined('ABSPATH')) exit;

define('CUSTOM_PASSWORD_PAGE_SLUG', 'password');
define('PASSWORD_REFERRER_COOKIE', 'pwd_referrer_data');

// Hardcoded page configurations - Add your specific pages here
$GLOBALS['protected_pages'] = [
    'homepage' => [
        'url' => home_url('/'),
        'title' => 'Homepage',
        'is_home' => true,
    ],
    'page-1' => [  
        'url' => home_url('/tier-2/'),  
        'title' => 'Tier 2',  
        'is_home' => false,
    ],
    'page-2' => [  
        'url' => home_url('/tier-3/'),  
        'title' => 'Tier 3',  
        'is_home' => false,
    ],
    // Add more pages as needed
];

/**
 * Redirect from password-protected pages to our custom password page
 */
function custom_password_redirect() {
    if (is_page(CUSTOM_PASSWORD_PAGE_SLUG)) return '';

    $post_id = get_the_ID();
    $is_home = is_front_page() || is_home();
    $permalink = $is_home ? home_url('/') : get_permalink($post_id);
    $post_title = get_the_title($post_id);
    $post_slug = $is_home ? 'homepage' : get_post_field('post_name', $post_id);

    // For homepage support
    if ($is_home && $post_id == 0) {
        $post_id = get_option('page_on_front');
        $post_title = get_the_title($post_id) ?: 'Homepage';
        $post_slug = 'homepage';
    }

    // Determine which page we're dealing with based on the current URL
    $current_page_type = 'homepage'; // Default to homepage
    foreach ($GLOBALS['protected_pages'] as $page_key => $page_data) {
        if ($permalink === $page_data['url'] || $post_slug === $page_key) {
            $current_page_type = $page_key;
            break;
        }
    }

    // Store the referrer data with our identified page type
    $referrer_data = [
        'id' => $post_id,
        'url' => $permalink,
        'title' => $post_title,
        'page_type' => $current_page_type,
        'is_home' => $is_home ? '1' : '0',
        'timestamp' => time(),
    ];

    // Set the cookie only if it doesn't already exist
    if (!isset($_COOKIE[PASSWORD_REFERRER_COOKIE])) {
        setcookie(PASSWORD_REFERRER_COOKIE, json_encode($referrer_data), time() + 3600, COOKIEPATH, COOKIE_DOMAIN, is_ssl(), true);
        error_log("Set PASSWORD_REFERRER_COOKIE: " . json_encode($referrer_data)); // Debugging
    } else {
        error_log("PASSWORD_REFERRER_COOKIE already exists."); // Debugging
    }

    // Redirect to our custom password page
    return '<script>
        localStorage.setItem("protected_page_data", ' . json_encode(json_encode($referrer_data)) . ');
        window.location.href = "' . esc_url(site_url('/' . CUSTOM_PASSWORD_PAGE_SLUG)) . '";
    </script>';
}
add_filter('the_password_form', 'custom_password_redirect');

/**
 * Render the custom password form shortcode
 */
function render_custom_password_form() {
    // Get referrer data from cookie or query params
    $referrer_data = isset($_COOKIE[PASSWORD_REFERRER_COOKIE]) ? json_decode(stripslashes($_COOKIE[PASSWORD_REFERRER_COOKIE]), true) : null;

    // Extract data from referrer
    $page_type = !empty($referrer_data['page_type']) ? $referrer_data['page_type'] : 'homepage';
    $post_id = !empty($referrer_data['id']) ? intval($referrer_data['id']) : 0;
    $is_home = !empty($referrer_data['is_home']) && $referrer_data['is_home'] === '1';

    // Get page information either from referrer or hardcoded config
    $return_url = !empty($referrer_data['url']) ? $referrer_data['url'] : $GLOBALS['protected_pages'][$page_type]['url'];
    $post_title = !empty($referrer_data['title']) ? $referrer_data['title'] : $GLOBALS['protected_pages'][$page_type]['title'];

    // Debug information (remove in production)
    $debug_info = "<script>console.log('Password form data:', " . json_encode([
        'page_type' => $page_type,
        'post_id' => $post_id, 
        'return_url' => $return_url,
        'is_home' => $is_home,
        'title' => $post_title,
        'referrer_data' => $referrer_data
    ]) . ");</script>";

    ob_start();
    echo $debug_info;
    ?>
    <div id="pw-status-message" style="text-align: center; min-height: 24px; margin-bottom: 15px;"></div>
    <script>
    document.addEventListener("DOMContentLoaded", function () {
        // Define the hardcoded pages (same as in PHP)
        const protectedPages = <?php echo json_encode($GLOBALS['protected_pages']); ?>;

        // Try to get data from localStorage if cookie failed
        const getReferrerData = function() {
            // First try from cookie data (provided by PHP)
            const cookieData = <?php echo json_encode($referrer_data); ?>;
            if (cookieData && cookieData.url) {
                console.log("Using referrer data from cookie");
                return cookieData;
            }
            // Then try from localStorage 
            try {
                const lsData = JSON.parse(localStorage.getItem("protected_page_data") || "null");
                if (lsData && lsData.url) {
                    console.log("Using referrer data from localStorage");
                    return lsData;
                }
            } catch (e) {
                console.error("Error parsing localStorage data:", e);
            }
            // Fallback to default (homepage)
            console.warn("Falling back to homepage data.");
            return {
                id: 0,
                url: protectedPages.homepage.url,
                title: protectedPages.homepage.title,
                page_type: 'homepage',
                is_home: "1"
            };
        };

        const referrerData = getReferrerData();
        console.log("Final referrer data:", referrerData);

        // Get the page type from the referrer data
        const pageType = referrerData.page_type || 'homepage';
        const pageInfo = protectedPages[pageType] || protectedPages.homepage;

        // Process forms
        const forms = document.querySelectorAll(".elementor-form");
        if (forms.length === 0) return;

        forms.forEach(form => {
            form.addEventListener("submit", function (e) {
                e.preventDefault();
                const input = form.querySelector("input[type='password']");
                const status = document.getElementById("pw-status-message");

                if (!input || !input.value) {
                    status.textContent = "Please enter a password.";
                    status.style.color = "#d63638";
                    return;
                }

                const password = input.value;
                status.textContent = "Checking password...";
                status.style.color = "#666";

                // Submit the password to WordPress
                fetch("<?php echo esc_url(site_url('/wp-login.php?action=postpass')); ?>", {
                    method: "POST",
                    headers: { "Content-Type": "application/x-www-form-urlencoded" },
                    credentials: "same-origin",
                    body: new URLSearchParams({ "post_password": password }),
                }).then(response => {
                    // Check if the session cookie is set by fetching the target URL
                    const targetUrl = referrerData.url || pageInfo.url;
                    console.log("Checking URL:", targetUrl);

                    return fetch(targetUrl, {
                        method: "GET",
                        credentials: "same-origin",
                        cache: "no-store", // Prevent caching
                        headers: {
                            'Cache-Control': 'no-cache, no-store, must-revalidate',
                            'Pragma': 'no-cache',
                            'Expires': '0',
                        },
                    });
                }).then(response => response.text()).then(html => {
                    // Log the response HTML for debugging
                    console.log("Response HTML:", html);

                    // Check if the page is still password protected
                    const isProtected = html.includes("post_password") ||
                                       html.includes("Protected Content") ||
                                       html.includes("post-password-form") ||
                                       html.includes("This content is password protected");

                    setTimeout(() => {
                        if (isProtected) {
                            status.textContent = "Incorrect password. Please try again.";
                            status.style.color = "#d63638";
                            input.focus();
                        } else {
                            status.textContent = "Password accepted. Redirecting...";
                            status.style.color = "#00a32a";
                            localStorage.removeItem("protected_page_data");
                            setTimeout(() => {
                                const targetUrl = referrerData.url || pageInfo.url;
                                console.log("Redirecting to:", targetUrl);
                                window.location.href = targetUrl;
                            }, 800);
                        }
                    }, 600);
                }).catch((error) => {
                    console.error("Password check error:", error);
                    setTimeout(() => {
                        status.textContent = "Error checking password.";
                        status.style.color = "#d63638";
                    }, 600);
                });
            });
        });
    });
    </script>
    <?php
    return ob_get_clean();
}
add_shortcode('custom_password_form', 'render_custom_password_form');

/**
 * Process direct form submissions (non-JS fallback)
 */
function process_direct_password_submission() {
    if (!is_page(CUSTOM_PASSWORD_PAGE_SLUG) || !isset($_POST['post_password'])) return;

    $referrer_data = isset($_COOKIE[PASSWORD_REFERRER_COOKIE]) ? json_decode(stripslashes($_COOKIE[PASSWORD_REFERRER_COOKIE]), true) : null;
    $page_type = !empty($referrer_data['page_type']) ? $referrer_data['page_type'] : 'homepage';
    $url = !empty($referrer_data['url']) ? $referrer_data['url'] : $GLOBALS['protected_pages'][$page_type]['url'];

    wp_redirect($url);
    exit;
}
add_action('template_redirect', 'process_direct_password_submission', 5);

/**
 * Add custom classes to the body for styling based on page type
 */
function add_page_type_body_class($classes) {
    if (is_page(CUSTOM_PASSWORD_PAGE_SLUG)) {
        $referrer_data = isset($_COOKIE[PASSWORD_REFERRER_COOKIE]) ? json_decode(stripslashes($_COOKIE[PASSWORD_REFERRER_COOKIE]), true) : null;
        $page_type = !empty($referrer_data['page_type']) ? $referrer_data['page_type'] : 'homepage';
        $classes[] = 'password-page-' . sanitize_html_class($page_type);
    }
    return $classes;
}
add_filter('body_class', 'add_page_type_body_class');

/**
 * Clean up tracking data after successful access
 */
function cleanup_password_tracking_data() {
    if (is_page(CUSTOM_PASSWORD_PAGE_SLUG) || !empty($_POST)) return;

    if (isset($_COOKIE[PASSWORD_REFERRER_COOKIE])) {
        setcookie(PASSWORD_REFERRER_COOKIE, '', time() - 3600, COOKIEPATH, COOKIE_DOMAIN, is_ssl(), true);
    }

    add_action('wp_footer', function () {
        echo '<script>localStorage.removeItem("protected_page_data");</script>';
    });
}
add_action('template_redirect', 'cleanup_password_tracking_data', 20);