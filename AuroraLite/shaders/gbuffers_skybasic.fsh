#version 120

uniform float rainStrength;
uniform float sunAngle;

varying vec2 texcoord;

void main() {
    vec3 day = vec3(0.34, 0.62, 0.92);
    vec3 dusk = vec3(0.95, 0.32, 0.18);
    float horizon = 1.0 - abs(texcoord.y * 2.0 - 1.0);
    float warm = smoothstep(0.25, 0.55, horizon) * (0.5 + 0.5 * cos(sunAngle * 6.28318));
    vec3 sky = mix(day, dusk, warm * 0.32);
    sky = mix(sky, vec3(0.20, 0.27, 0.36), rainStrength * 0.45);
    gl_FragColor = vec4(sky, 1.0);
}
