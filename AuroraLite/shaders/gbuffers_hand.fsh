#version 120

uniform sampler2D gtexture;
uniform sampler2D lightmap;

varying vec2 texcoord;
varying vec2 lmcoord;
varying vec4 vertColor;
varying vec3 viewNormal;
varying vec3 viewPos;

void main() {
    vec4 tex = texture2D(gtexture, texcoord) * vertColor;
    if (tex.a < 0.1) discard;
    vec3 light = texture2D(lightmap, lmcoord).rgb;
    gl_FragColor = vec4(tex.rgb * light, tex.a);
}
