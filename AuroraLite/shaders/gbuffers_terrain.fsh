#version 120

uniform sampler2D gtexture;
uniform sampler2D lightmap;
uniform float rainStrength;

varying vec2 texcoord;
varying vec2 lmcoord;
varying vec4 vertColor;
varying vec3 viewNormal;
varying vec3 viewPos;

void main() {
    vec4 tex = texture2D(gtexture, texcoord) * vertColor;
    if (tex.a < 0.1) discard;

    vec3 light = texture2D(lightmap, lmcoord).rgb;
    float skyLight = max(light.r, light.g);
    float side = 0.82 + 0.18 * max(viewNormal.y, 0.0);
    vec3 color = tex.rgb * light * side;
    color *= mix(vec3(1.0), vec3(0.82, 0.90, 1.0), rainStrength * 0.35);

    gl_FragColor = vec4(color, tex.a);
}
