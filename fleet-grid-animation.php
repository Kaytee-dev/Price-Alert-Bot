<?php
/**
 * Plugin Name: Fleet Grid Animation
 * Description: Subtle wave-based animated grid with node glow.
 * Version: 2.0
 * Author: You
 */

function fleet_enqueue_grid_script() {
    if (!is_admin() && did_action('elementor/loaded')) {
        wp_enqueue_script(
            'fleet-grid-animation',
            plugin_dir_url(__FILE__) . 'grid-animation.js',
            array('jquery'),
            '2.0',
            true
        );
    }
}
add_action('wp_enqueue_scripts', 'fleet_enqueue_grid_script');

function fleet_grid_animation_shortcode($atts) {
    $atts = shortcode_atts(array(
        'brand_color'    => '#CC6802',
        'glow_radius'    => '5',
        'glow_opacity'   => '0.1',
        'grid_spacing'   => '50',
        'wave_speed'     => '1.5',
        'node_size'      => '2',
        'z_index'        => '-1'
    ), $atts, 'fleet_grid_animation');

    ob_start(); ?>
    <div class="fleet-grid-wrapper" style="position: fixed; inset: 0; z-index: <?php echo esc_attr($atts['z_index']); ?>; pointer-events: none; overflow: hidden;">
        <canvas id="fleetGridCanvas" style="width:100%; height:100%; display:block;"></canvas>
    </div>
    <script>
    window.fleetGridSettings = {
        brandColor: "<?php echo esc_js($atts['brand_color']); ?>",
        glowRadius: "<?php echo esc_js($atts['glow_radius']); ?>",
        glowOpacity: "<?php echo esc_js($atts['glow_opacity']); ?>",
        gridSpacing: "<?php echo esc_js($atts['grid_spacing']); ?>",
        waveSpeed: "<?php echo esc_js($atts['wave_speed']); ?>",
        nodeSize: "<?php echo esc_js($atts['node_size']); ?>"
    };
    </script>
    <?php return ob_get_clean();
}
add_shortcode('fleet_grid_animation', 'fleet_grid_animation_shortcode');
