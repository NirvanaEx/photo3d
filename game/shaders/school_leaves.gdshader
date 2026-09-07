shader_type spatial;
render_mode cull_disabled;
uniform vec4 leaf_color : source_color = vec4(0.18,0.29,0.07,1.0);
void vertex() {
    vec3 world = (MODEL_MATRIX * vec4(VERTEX,1.0)).xyz;
    float gust = sin(TIME*1.4+world.x*0.53+world.z*0.41);
    VERTEX.x += gust*0.018*sin(world.y*3.1+world.z);
    VERTEX.z += sin(TIME*1.1+world.x)*0.012;
}
void fragment() {
    ALBEDO = leaf_color.rgb;
    ROUGHNESS = 0.78;
    BACKLIGHT = leaf_color.rgb * 0.14;
}
