#version 120

uniform sampler2D colortex0;
uniform sampler2D depthtex0;
uniform vec2 viewSize;
uniform float rainStrength;

varying vec2 texcoord;

void main() {
    vec3 color = texture2D(colortex0, texcoord).rgb;
    float depth = texture2D(depthtex0, texcoord).r;

    vec2 p = texcoord * 2.0 - 1.0;
    float vignette = 1.0 - 0.12 * dot(p, p);
    color *= vignette;

    float fog = smoothstep(0.72, 1.0, depth);
    color = mix(color, color * vec3(0.86, 0.93, 1.0), fog * rainStrength * 0.18);
    gl_FragColor = vec4(color, 1.0);
}
