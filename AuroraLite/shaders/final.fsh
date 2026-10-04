#version 120

uniform sampler2D colortex0;

varying vec2 texcoord;

void main() {
    vec3 c = texture2D(colortex0, texcoord).rgb;
    c = max(c, vec3(0.0));
    c = c / (c + vec3(1.0));
    c = pow(c, vec3(0.92));
    gl_FragColor = vec4(c, 1.0);
}
